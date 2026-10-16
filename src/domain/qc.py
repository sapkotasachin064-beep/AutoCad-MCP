"""Read-only drawing checks over a normalised entity snapshot (pure).

Input is the snapshot both backends produce (snapshot_entities: handle,
type, layer, points / center / radius / text / length / closed ...). Every
rule is a function of that snapshot only, so the checks are identical on the
live and headless backends and fully unit-testable. Rules report findings;
nothing is ever changed.

These are drafting hygiene checks, not code or standards compliance.
"""

import math
import re
from collections import Counter, defaultdict

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
