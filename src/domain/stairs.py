"""Straight-flight stair calculator and plan planner (pure).

The calculator splits a floor-to-floor rise into equal risers no taller than
max_riser, picks a going (tread depth) of at least min_tread that keeps the
step relation 2R + G inside a comfort band, and reports the run length and
pitch. The defaults are common rules of thumb for residential stairs --
max riser 190 mm, min going 250 mm, 2R + G between 550 and 700 mm, pitch at
most 42 degrees -- NOT any particular building code. Pass the limits your
project's code requires; the result always states which limits it used and
never claims compliance with anything else. Headroom, handrails, landings
for long flights and fire rules are not checked.
"""

import math

from domain import units
from domain.plan import Plan, Primitive, rect_points
from utils import geometry

DEFAULT_LIMITS_MM = {
    "max_riser": 190.0,
    "min_tread": 250.0,
    "step_relation_min": 550.0,  # 2R + G
    "step_relation_max": 700.0,
    "max_pitch_degrees": 42.0,
}


def design_stair(floor_to_floor, unit_code: int, *, max_riser=None, min_tread=None, tread=None,
                 width=None, step_relation_min=None, step_relation_max=None, max_pitch_degrees=None) -> dict:
    """All lengths in and out are in unit_code units."""
    rise = geometry.validate_positive(floor_to_floor, "floor_to_floor")
    mm = units.unit_code("mm")
    to_mm = units.convert(1.0, unit_code, mm)
    from_mm = 1.0 / to_mm

    def limit(value, key):
        return geometry.validate_positive(value, key) * to_mm if value is not None else DEFAULT_LIMITS_MM[key]

    lim = {k: limit(v, k) for k, v in (("max_riser", max_riser), ("min_tread", min_tread),
                                       ("step_relation_min", step_relation_min),
                                       ("step_relation_max", step_relation_max))}
    lim["max_pitch_degrees"] = (geometry.validate_positive(max_pitch_degrees, "max_pitch_degrees")
                                if max_pitch_degrees is not None else DEFAULT_LIMITS_MM["max_pitch_degrees"])
    if lim["step_relation_min"] >= lim["step_relation_max"]:
        raise geometry.ValidationError("step_relation_min must be below step_relation_max")

    rise_mm = rise * to_mm
    risers = max(2, math.ceil(rise_mm / lim["max_riser"] - 1e-9))
    riser = rise_mm / risers
    if tread is not None:
        going = geometry.validate_positive(tread, "tread") * to_mm
    else:
        # Aim for the middle of the comfort band, never below min_tread.
        target = (lim["step_relation_min"] + lim["step_relation_max"]) / 2.0
        going = max(lim["min_tread"], target - 2 * riser)
    treads = risers - 1
    relation = 2 * riser + going
    pitch = math.degrees(math.atan2(riser, going))
    checks = [
        {"rule": "riser <= max_riser", "value": round(riser, 2), "limit": lim["max_riser"], "ok": riser <= lim["max_riser"] + 1e-9},
        {"rule": "going >= min_tread", "value": round(going, 2), "limit": lim["min_tread"], "ok": going >= lim["min_tread"] - 1e-9},
        {"rule": "2R + G within band", "value": round(relation, 2),
         "limit": [lim["step_relation_min"], lim["step_relation_max"]],
         "ok": lim["step_relation_min"] - 1e-9 <= relation <= lim["step_relation_max"] + 1e-9},
        {"rule": "pitch <= max_pitch_degrees", "value": round(pitch, 2), "limit": lim["max_pitch_degrees"],
         "ok": pitch <= lim["max_pitch_degrees"] + 1e-9},
    ]
    w = geometry.validate_positive(width, "width") if width is not None else 900.0 * from_mm
    return {
        "unit": units.describe(unit_code),
        "floor_to_floor": rise,
        "risers": risers,
        "riser_height": riser * from_mm,
        "treads": treads,
        "tread_depth": going * from_mm,
        "run_length": treads * going * from_mm,
        "width": w,
        "step_relation_2R_plus_G": relation * from_mm,
        "pitch_degrees": pitch,
        "checks": checks,
        "all_checks_pass": all(c["ok"] for c in checks),
        "limits_used_mm": lim,
        "limits_source": "caller" if any(v is not None for v in (max_riser, min_tread, step_relation_min,
                                                                   step_relation_max, max_pitch_degrees))
        else "rule_of_thumb_defaults_not_a_building_code",
        "not_checked": ["headroom", "handrails and guards", "landing lengths", "fire and egress rules",
                        "local building code"],
    }


def plan_stair(design: dict, unit_code: int, drawing_code: int, *, origin=(0.0, 0.0), direction_degrees=90.0,
               text_height=None) -> Plan:
    """Plan view of a straight flight: outline, tread nosings, walking line
    with arrow and 'UP n R' note. direction_degrees is the climbing direction
    (90 = +Y). Only 0/90/180/270 are supported."""
    direction = geometry.validate_number(direction_degrees, "direction_degrees") % 360
    if direction not in (0, 90, 180, 270):
        raise geometry.ValidationError("direction_degrees must be 0, 90, 180 or 270")
    f = units.convert(1.0, unit_code, drawing_code)
    ox = geometry.validate_number(origin[0], "origin.x")
    oy = geometry.validate_number(origin[1], "origin.y")
    run = design["run_length"] * f
    width = design["width"] * f
    going = design["tread_depth"] * f
    th = (geometry.validate_positive(text_height, "text_height") * f) if text_height is not None \
        else units.convert(150.0, units.unit_code("mm"), drawing_code)

    # Build along +Y from (0,0), then rotate about the origin into direction.
    def place(x, y):
        if direction == 90:
            return (ox + x, oy + y, 0.0)
        if direction == 0:
            return (ox + y, oy - x, 0.0)
        if direction == 270:
            return (ox - x, oy - y, 0.0)
        return (ox - y, oy + x, 0.0)

    plan = Plan()
    plan.layer("A-FLOR-STRS", 2)
    plan.layer("A-ANNO-NOTE", 7)
    outline = tuple(place(*p[:2]) for p in rect_points(0.0, 0.0, width, run))
    plan.add(Primitive("polyline", "A-FLOR-STRS", "stair:outline", points=outline, closed=True, polyline_kind="2d"))
    for k in range(1, design["treads"]):
        y = k * going
        plan.add(Primitive("line", "A-FLOR-STRS", f"stair:nosing:{k}", points=(place(0.0, y), place(width, y))))
    cx = width / 2.0
    plan.add(Primitive("polyline", "A-FLOR-STRS", "stair:walkline", polyline_kind="2d",
                       points=(place(cx, going * 0.5), place(cx, run - going * 0.5))))
    head = min(width * 0.15, going * 0.8)
    tip = place(cx, run - going * 0.5)
    plan.add(Primitive("polyline", "A-FLOR-STRS", "stair:arrow", polyline_kind="2d",
                       points=(place(cx - head / 2, run - going * 0.5 - head), tip,
                               place(cx + head / 2, run - going * 0.5 - head))))
    plan.add(Primitive("mtext", "A-ANNO-NOTE", "stair:note", text=f"UP {design['risers']}R",
                       location=place(cx, going * 0.5 - th * 1.5), height=th, width=0.0,
                       attach="middle_center"))
    plan.meta = {"design": design, "footprint": {"width": width, "run": run},
                 "drawing_unit": units.describe(drawing_code)}
    return plan
