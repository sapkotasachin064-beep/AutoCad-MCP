"""Pure analysis logic: drawing QC, quantity takeoff and DXF diff. No pywin32,
no ezdxf.
"""

import math
import re
from collections import Counter, defaultdict

from domain import units


# ======= qc.py =======

RULES = {
    "zero_length": ("error", "line or polyline with (near) zero length"),
    "degenerate_polyline": ("error", "polyline with fewer than 2 distinct vertices"),
    "tiny_circle": ("warning", "circle or arc with (near) zero radius"),
    "duplicate": ("warning", "entity identical to another (same type, layer and geometry)"),
    "empty_text": ("warning", "TEXT/MTEXT with no visible characters"),
    "on_layer_0": ("info", "geometry drawn on layer 0 instead of a named layer"),
    "unclosed_wall_outline": ("warning", "polyline on a wall layer (A-WALL*) that is not closed"),
    "layer_name": ("info", "layer name does not match the required pattern"),
    "text_height_variety": ("info", "many different text heights (inconsistent annotation)"),
}
DEFAULT_RULES = tuple(r for r in RULES if r != "layer_name")


def _round(values, ndigits):
    return tuple(round(float(v), ndigits) for v in values)


def signature(e: dict, ndigits: int = 6):
    kind = e.get("type")
    if kind in ("LINE", "LWPOLYLINE", "POLYLINE3D", "POLYLINE"):
        pts = [tuple(_round(p[:2], ndigits)) for p in e.get("points") or []]
        if kind == "LINE":
            pts = sorted(pts)  # a reversed line is the same line
        return (kind, e.get("layer"), tuple(pts), e.get("closed"))
    if kind in ("CIRCLE", "ARC"):
        return (kind, e.get("layer"), _round((e.get("center") or [0, 0])[:2], ndigits), round(e.get("radius") or 0, ndigits),
                round(e.get("start_angle_degrees") or 0, 3), round(e.get("end_angle_degrees") or 0, 3))
    if kind in ("TEXT", "MTEXT"):
        return (kind, e.get("layer"), e.get("text"), _round((e.get("insertion_point") or [0, 0])[:2], ndigits))
    if kind == "INSERT":
        return (kind, e.get("layer"), e.get("block"), _round((e.get("insertion_point") or [0, 0])[:2], ndigits))
    return None


def check(entities: list[dict], *, rules=None, tolerance: float = 1e-6, layer_pattern: str | None = None,
          layers: list[str] | None = None, max_text_heights: int = 6, max_issues: int = 200) -> dict:
    selected = list(rules) if rules else list(DEFAULT_RULES)
    if layer_pattern and "layer_name" not in selected:
        selected.append("layer_name")
    unknown = [r for r in selected if r not in RULES]
    if unknown:
        raise ValueError(f"unknown rules {unknown}; known: {sorted(RULES)}")
    pattern = re.compile(layer_pattern) if layer_pattern else None

    issues = []

    def add(rule, e, message, **extra):
        severity = RULES[rule][0]
        issues.append({"rule": rule, "severity": severity, "handle": e.get("handle"), "layer": e.get("layer"),
                       "type": e.get("type"), "message": message, **extra})

    seen = {}
    heights = Counter()
    for e in entities:
        kind = e.get("type")
        if kind in ("LINE", "LWPOLYLINE", "POLYLINE3D", "POLYLINE"):
            pts = e.get("points") or []
            distinct = {tuple(round(c, 9) for c in p[:3]) for p in pts}
            if "degenerate_polyline" in selected and kind != "LINE" and len(distinct) < 2:
                add("degenerate_polyline", e, f"{len(distinct)} distinct vertex(es)")
            elif "zero_length" in selected and (e.get("length") is not None and e["length"] <= tolerance):
                add("zero_length", e, f"length {e['length']}")
            if ("unclosed_wall_outline" in selected and kind != "LINE" and str(e.get("layer", "")).upper().startswith("A-WALL")
                    and not e.get("closed")):
                add("unclosed_wall_outline", e, "wall outline polyline is open")
        if kind in ("CIRCLE", "ARC") and "tiny_circle" in selected and (e.get("radius") or 0) <= tolerance:
            add("tiny_circle", e, f"radius {e.get('radius')}")
        if kind in ("TEXT", "MTEXT"):
            if e.get("height"):
                heights[round(float(e["height"]), 6)] += 1
            visible = re.sub(r"\\[A-Za-z][^;\\]*;|\\P|[{}]", "", e.get("text") or "").strip()
            if "empty_text" in selected and not visible:
                add("empty_text", e, "no visible characters")
        if "on_layer_0" in selected and e.get("layer") == "0" and kind not in (None,):
            add("on_layer_0", e, "drawn on layer 0")
        if "duplicate" in selected:
            sig = signature(e)
            if sig is not None:
                if sig in seen:
                    add("duplicate", e, f"duplicates {seen[sig]}", duplicate_of=seen[sig])
                else:
                    seen[sig] = e.get("handle")

    layer_findings = []
    if "layer_name" in selected and pattern is not None:
        for name in sorted(set(layers or [e.get("layer") for e in entities if e.get("layer")])):
            if name not in ("0", "Defpoints") and not pattern.fullmatch(name):
                layer_findings.append({"rule": "layer_name", "severity": RULES["layer_name"][0], "layer": name,
                                       "message": f"layer {name!r} does not match {layer_pattern!r}"})
    if "text_height_variety" in selected and len(heights) > max_text_heights:
        layer_findings.append({"rule": "text_height_variety", "severity": RULES["text_height_variety"][0],
                               "message": f"{len(heights)} different text heights (more than {max_text_heights})",
                               "heights": sorted(heights)})

    all_issues = issues + layer_findings
    by_rule = Counter(i["rule"] for i in all_issues)
    by_severity = Counter(i["severity"] for i in all_issues)
    return {
        "rules_run": selected,
        "entity_count": len(entities),
        "issue_count": len(all_issues),
        "counts_by_rule": {r: by_rule.get(r, 0) for r in selected},
        "counts_by_severity": dict(by_severity),
        "passed": by_severity.get("error", 0) == 0,
        "issues": all_issues[:max_issues],
        "issues_truncated": len(all_issues) > max_issues,
        "text_heights": dict(sorted(heights.items())),
        "rule_descriptions": {r: RULES[r][1] for r in selected},
        "note": "Drafting hygiene checks only; not building-code or standards compliance.",
    }


def group_by_layer(entities):
    groups = defaultdict(list)
    for e in entities:
        groups[e.get("layer")].append(e)
    return groups


def distance(a, b):
    return math.dist(a[:2], b[:2])


# ======= takeoff.py =======



def _closed_area(points):
    pts = [p[:2] for p in points]
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2.0


def _perimeter(points, closed):
    seq = list(points) + ([points[0]] if closed and points else [])
    return sum(math.dist(a[:2], b[:2]) for a, b in zip(seq, seq[1:]))


def _wall_dims(points):
    """(length, thickness) of a 4-vertex wall outline, else None."""
    if len(points) != 4:
        return None
    sides = [math.dist(points[i][:2], points[(i + 1) % 4][:2]) for i in range(4)]
    a, b = (sides[0] + sides[2]) / 2.0, (sides[1] + sides[3]) / 2.0
    return (max(a, b), min(a, b))


def takeoff(entities: list[dict], insunits: int | None, *, layers=None, wall_height=None) -> dict:
    wanted = {name.lower() for name in layers} if layers else None
    per_layer = defaultdict(lambda: {
        "line_length": 0.0, "open_polyline_length": 0.0, "arc_length": 0.0,
        "closed_polylines": 0, "closed_area": 0.0, "closed_perimeter": 0.0,
        "circles": 0, "circle_area": 0.0, "hatch_area": 0.0, "hatches": Counter(),
        "blocks": Counter(), "texts": 0, "entities": 0,
        "walls": {"count": 0, "length": 0.0, "plan_area": 0.0, "thicknesses": Counter()},
    })
    for e in entities:
        layer = e.get("layer") or "0"
        if wanted is not None and layer.lower() not in wanted:
            continue
        row = per_layer[layer]
        row["entities"] += 1
        kind = e.get("type")
        if kind == "LINE":
            row["line_length"] += e.get("length") or math.dist(e["points"][0], e["points"][1])
        elif kind in ("LWPOLYLINE", "POLYLINE3D", "POLYLINE"):
            pts = e.get("points") or []
            if e.get("closed"):
                row["closed_polylines"] += 1
                area = e.get("area") if e.get("area") is not None else _closed_area(pts)
                row["closed_area"] += area
                row["closed_perimeter"] += e.get("length") or _perimeter(pts, True)
                if layer.upper().startswith("A-WALL"):
                    dims = _wall_dims(pts)
                    if dims:
                        row["walls"]["count"] += 1
                        row["walls"]["length"] += dims[0]
                        row["walls"]["plan_area"] += dims[0] * dims[1]
                        row["walls"]["thicknesses"][round(dims[1], 4)] += 1
            else:
                row["open_polyline_length"] += e.get("length") or _perimeter(pts, False)
        elif kind == "ARC":
            row["arc_length"] += e.get("length") or 0.0
        elif kind == "CIRCLE":
            row["circles"] += 1
            row["circle_area"] += math.pi * (e.get("radius") or 0.0) ** 2
        elif kind == "HATCH":
            if e.get("area") is not None:
                row["hatch_area"] += e["area"]
            row["hatches"][e.get("pattern") or "?"] += 1
        elif kind == "INSERT":
            row["blocks"][e.get("block") or "?"] += 1
        elif kind in ("TEXT", "MTEXT"):
            row["texts"] += 1

    to_m = None
    if insunits not in (None, 0) and insunits in units.INSUNITS and units.INSUNITS[insunits][1]:
        to_m = units.convert(1.0, insunits, units.unit_code("m"))

    layers_out = {}
    totals = Counter()
    for layer, row in sorted(per_layer.items()):
        out = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in row.items()
               if k not in ("hatches", "blocks", "walls")}
        out["hatches"] = dict(row["hatches"])
        out["blocks"] = dict(row["blocks"])
        walls = row["walls"]
        if walls["count"]:
            out["walls"] = {"count": walls["count"], "length": round(walls["length"], 6),
                            "thicknesses": {str(k): v for k, v in walls["thicknesses"].items()}}
            out["walls"]["plan_area"] = round(walls["plan_area"], 6)
            if wall_height:
                out["walls"]["face_area_one_side"] = round(walls["length"] * wall_height, 6)
                out["walls"]["volume_estimate"] = round(walls["plan_area"] * wall_height, 6)
        if to_m is not None:
            length = row["line_length"] + row["open_polyline_length"] + row["arc_length"]
            out["metric"] = {
                "total_length_m": round(length * to_m, 4),
                "closed_area_m2": round(row["closed_area"] * to_m * to_m, 4),
                "circle_area_m2": round(row["circle_area"] * to_m * to_m, 4),
                "hatch_area_m2": round(row["hatch_area"] * to_m * to_m, 4),
            }
            if walls["count"]:
                out["metric"]["wall_length_m"] = round(walls["length"] * to_m, 4)
        layers_out[layer] = out
        for k in ("line_length", "open_polyline_length", "arc_length", "closed_area", "circle_area", "hatch_area"):
            totals[k] += row[k]
        totals["entities"] += row["entities"]
    return {
        "drawing_unit": units.describe(insunits) if insunits is not None else None,
        "metres_per_drawing_unit": to_m,
        "layers": layers_out,
        "totals": {k: round(v, 6) for k, v in totals.items()},
        "note": "Measured geometry only; not a professional bill of quantities (no waste, laps, opening deductions or rates).",
    }


# ======= diff.py =======
COMPARED_FIELDS = ("type", "layer", "points", "closed", "center", "radius", "start_angle_degrees",
                   "end_angle_degrees", "text", "insertion_point", "height", "block", "pattern")


def _norm(value, ndigits=6):
    if isinstance(value, float):
        return round(value, ndigits)
    if isinstance(value, (list, tuple)):
        return [_norm(v, ndigits) for v in value]
    return value


def compare(old: list[dict], new: list[dict], *, max_items: int = 200) -> dict:
    old_by_handle = {e["handle"]: e for e in old if e.get("handle")}
    new_by_handle = {e["handle"]: e for e in new if e.get("handle")}
    changed, unchanged = [], 0
    for handle in sorted(old_by_handle.keys() & new_by_handle.keys()):
        a, b = old_by_handle[handle], new_by_handle[handle]
        fields = [f for f in COMPARED_FIELDS if _norm(a.get(f)) != _norm(b.get(f))]
        if fields:
            changed.append({"handle": handle, "type": b.get("type"), "layer": b.get("layer"), "fields": fields,
                            "before": {f: a.get(f) for f in fields}, "after": {f: b.get(f) for f in fields}})
        else:
            unchanged += 1
    removed = [old_by_handle[h] for h in sorted(old_by_handle.keys() - new_by_handle.keys())]
    added = [new_by_handle[h] for h in sorted(new_by_handle.keys() - old_by_handle.keys())]

    # Re-pair removed/added entities that are geometrically identical (new handle, same thing).
    added_by_sig = {}
    for e in added:
        added_by_sig.setdefault(signature(e), []).append(e)
    moved_handles, still_removed = [], []
    for e in removed:
        sig = signature(e)
        if sig is not None and added_by_sig.get(sig):
            twin = added_by_sig[sig].pop()
            moved_handles.append({"old_handle": e["handle"], "new_handle": twin["handle"], "type": e.get("type"),
                                  "layer": e.get("layer")})
        else:
            still_removed.append(e)
    rehandled = {m["new_handle"] for m in moved_handles}
    still_added = [e for e in added if e["handle"] not in rehandled]

    def brief(e):
        return {k: e.get(k) for k in ("handle", "type", "layer", "text", "block") if e.get(k) is not None}

    return {
        "summary": {"unchanged": unchanged, "changed": len(changed), "added": len(still_added),
                    "removed": len(still_removed), "same_geometry_new_handle": len(moved_handles),
                    "old_count": len(old), "new_count": len(new)},
        "changed": changed[:max_items],
        "added": [brief(e) for e in still_added[:max_items]],
        "removed": [brief(e) for e in still_removed[:max_items]],
        "same_geometry_new_handle": moved_handles[:max_items],
        "truncated": any(len(x) > max_items for x in (changed, still_added, still_removed, moved_handles)),
        "identical": not changed and not still_added and not still_removed,
    }
