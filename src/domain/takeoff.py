"""Quantities measured from drawing geometry (pure; works on the normalised
snapshot both backends produce).

Per layer: total length of lines, open polylines and arcs; count, area and
perimeter of closed polylines and circles; hatch areas by pattern; block
counts by name; text count. Wall layers (A-WALL*) also get an estimate of
wall length from their outline polylines (the longer side of each 4-vertex
outline) and, if a wall height is given, face area and volume.

These are geometric measurements of what is drawn, in the drawing's units
and converted to metres when INSUNITS is known -- an aid for a takeoff, not
a professional bill of quantities: no waste, laps, openings deductions or
rates are applied.
"""

import math
from collections import Counter, defaultdict

from domain import units


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
