"""Architectural drawing macros as pure plans: a parametric staircase, a column grid, a window cut into a
wall, and furniture or sanitary stamps. No pywin32, no ezdxf.

Each planner returns a domain.architecture.Plan that backends.targets.emit draws on either backend, so the
macros need no engine-specific code. Lengths a caller gives are multiplied by `factor`
(units.length_factor); everything else -- default sizes, text and dimension parts -- follows the drawing's
own units. A metric drawing gets round millimetre sizes (300 x 300 column, 900 stair, 1200 window), an
imperial drawing round inch sizes (9 x 12 column, 36 in stair, 48 in window), and annotation prints the same
size on paper in both (units.annotation_scale). The sizes are drafting conventions, not code requirements,
and every one can be overridden by the caller.
"""

import contextlib
import math

from domain import units
from domain.architecture import Plan, Primitive, letters
from utils import geometry
from utils.constants import ARCHITECTURAL_LAYERS

MM, INCH = 4, 1  # INSUNITS codes

MAX_RISERS = 60
MAX_COLUMNS = 2000
MAX_WALLS_SCANNED = 5000

# layer -> (ACI colour, what is on it). Colours apply only when the layer is created.
STAIR_LAYERS = {
    "A-FLOR-TRED": (2, "stair treads"),
    "A-FLOR-RISR": (8, "stair risers"),
    "A-FLOR-LAND": (3, "stair landing"),
    "A-FLOR-HRAL": (4, "handrails"),
    "A-ANNO-SYMB": (6, "walking-line arrow"),
    "A-ANNO-NOTE": (7, "UP / DN note"),
}
COLUMN_LAYERS = {
    "COLUMNS": (5, "column outlines and their solid fill"),
    "COLUMNS-TEXT": (7, "column marks"),
    "COLUMNS-DIM": (6, "grid dimensions"),
}
WINDOW_LAYERS = {
    "A-GLAZ": (4, "glass pane lines and mullions"),
    "A-GLAZ-SILL": (4, "sill lines"),
    "A-GLAZ-IDEN": (7, "window tags"),
}
FURNITURE_LAYERS = {
    "A-FURN": (30, "furniture and fixtures"),
    "A-FURN-TEXT": (7, "furniture labels"),
}
LAYERS = {name: {"color_index": color, "purpose": purpose}
          for group in (STAIR_LAYERS, COLUMN_LAYERS, WINDOW_LAYERS, FURNITURE_LAYERS)
          for name, (color, purpose) in group.items()}

# ======= default sizes =======
# Natural round sizes of each unit system (not conversions of one another): the metric table is in
# millimetres, the imperial table in inches. Pairs are (width, depth) unless noted.

_METRIC = (MM, {
    "stair_width": 900.0, "tread_depth": 250.0, "rail_width": 50.0, "rail_inset": 75.0,
    "column": (300.0, 300.0),
    "W1": (1200.0, 1200.0, 900.0),  # window: width, height, sill height
    "W2": (1800.0, 1200.0, 900.0),
    "W3": (600.0, 450.0, 1800.0),
    "bed_single": (900.0, 1900.0), "bed_double": (1500.0, 2000.0), "bed_king": (1800.0, 2000.0),
    "bed_headboard": 80.0, "bed_pillow": (500.0, 350.0), "bed_pillow_gap": 60.0, "bed_margin": 50.0,
    "dining_pitch": 600.0, "dining_table_depth": 900.0, "dining_table_min": 900.0, "dining_chair": 450.0,
    "dining_tuck": 100.0, "dining_chair_back": 60.0,
    "sofa_seat_pitch": 600.0, "sofa_arm": 150.0, "sofa_depth": 900.0, "sofa_back": 200.0,
    "sofa_coffee": (1100.0, 600.0), "sofa_armchair": 850.0, "sofa_gap": 450.0, "sofa_side_gap": 150.0,
    "wc_width": 360.0, "wc_depth": 700.0,
    "kitchen_length": 2400.0, "kitchen_depth": 600.0, "kitchen_return": 1800.0,
    "kitchen_sink": (800.0, 460.0), "kitchen_hob": (580.0, 500.0),
})
_IMPERIAL = (INCH, {
    "stair_width": 36.0, "tread_depth": 10.0, "rail_width": 2.0, "rail_inset": 3.0,
    "column": (9.0, 12.0),
    "W1": (48.0, 48.0, 36.0),
    "W2": (72.0, 48.0, 36.0),
    "W3": (24.0, 18.0, 72.0),
    "bed_single": (39.0, 75.0), "bed_double": (60.0, 80.0), "bed_king": (76.0, 80.0),
    "bed_headboard": 3.0, "bed_pillow": (20.0, 14.0), "bed_pillow_gap": 2.0, "bed_margin": 2.0,
    "dining_pitch": 24.0, "dining_table_depth": 36.0, "dining_table_min": 36.0, "dining_chair": 18.0,
    "dining_tuck": 4.0, "dining_chair_back": 2.0,
    "sofa_seat_pitch": 24.0, "sofa_arm": 6.0, "sofa_depth": 36.0, "sofa_back": 8.0,
    "sofa_coffee": (44.0, 24.0), "sofa_armchair": 34.0, "sofa_gap": 18.0, "sofa_side_gap": 6.0,
    "wc_width": 14.0, "wc_depth": 28.0,
    "kitchen_length": 96.0, "kitchen_depth": 24.0, "kitchen_return": 72.0,
    "kitchen_sink": (32.0, 18.0), "kitchen_hob": (24.0, 20.0),
})

WINDOW_TYPES = {
    "W1": {"name": "standard window", "sashes": 2},
    "W2": {"name": "wide window", "sashes": 3},
    "W3": {"name": "ventilator", "sashes": 1},
}

FURNITURE_TYPES = {
    "bed": {"label": "BED", "variants": ("single", "double", "king"), "default_variant": "double"},
    "dining_table": {"label": "DINING TABLE", "variants": (), "default_variant": None},
    "sofa_set": {"label": "SOFA SET", "variants": (), "default_variant": None},
    "wc": {"label": "WC", "variants": (), "default_variant": None},
    "kitchen_countertop": {"label": "KITCHEN", "variants": ("straight", "l_left", "l_right"),
                           "default_variant": "straight"},
}


def _scaled(value, factor):
    if isinstance(value, tuple):
        return tuple(v * factor for v in value)
    return value * factor


def sizes(drawing_code: int) -> dict:
    """Default macro sizes in the drawing's own units (the metric table for metric drawings, the imperial
    table for imperial ones). A drawing without fixed units raises E_UNITS_MISMATCH."""
    table_unit, table = _METRIC if units.is_metric(drawing_code) else _IMPERIAL
    factor = units.mm_per_unit(table_unit) / units.mm_per_unit(drawing_code)
    return {name: _scaled(value, factor) for name, value in table.items()}


def window_catalog(drawing_code: int) -> dict:
    """W1-W3 with width, height and sill height in the drawing's units."""
    std = sizes(drawing_code)
    return {tag: {**info, "width": std[tag][0], "height": std[tag][1], "sill_height": std[tag][2]}
            for tag, info in WINDOW_TYPES.items()}


# ======= helpers =======


def _r(value: float) -> float:
    """Round away floating noise from rotated coordinates (and turn -0.0 into 0.0)."""
    return round(value, 9) + 0.0


class Frame:
    """A 2D frame in the drawing: local +u points along `angle_degrees`, local +v is u turned 90 degrees
    counterclockwise. pt() maps local coordinates to drawing coordinates at elevation 0."""

    def __init__(self, origin, angle_degrees: float = 0.0):
        self.origin = (float(origin[0]), float(origin[1]))
        self.angle = float(angle_degrees)
        a = math.radians(self.angle)
        self._c, self._s = math.cos(a), math.sin(a)

    def pt(self, u: float, v: float = 0.0) -> tuple:
        return (_r(self.origin[0] + u * self._c - v * self._s), _r(self.origin[1] + u * self._s + v * self._c), 0.0)

    def rect(self, u0, v0, u1, v1) -> tuple:
        return (self.pt(u0, v0), self.pt(u1, v0), self.pt(u1, v1), self.pt(u0, v1))


def _xy(point, label: str) -> tuple:
    p = geometry.validate_point_2d_or_3d(point, label)
    return (p[0], p[1])


def _count(value, label: str, low: int, high: int) -> int:
    ok = (not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
          and value == int(value))
    if not ok:
        raise geometry.ValidationError(f"{label} must be a whole number, got {value!r}")
    value = int(value)
    if not low <= value <= high:
        raise geometry.ValidationError(f"{label} must be between {low} and {high}, got {value}")
    return value


def _non_negative(value, label: str) -> float:
    number = geometry.validate_number(value, label)
    if number < 0:
        raise geometry.ValidationError(f"{label} must not be negative, got {number}")
    return number


def _flag(value, label: str) -> bool:
    if not isinstance(value, bool):
        raise geometry.ValidationError(f"{label} must be true or false, got {value!r}")
    return value


def _pair(value, label: str) -> tuple:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise geometry.ValidationError(f"{label} must be [width, depth]")
    return (geometry.validate_positive(value[0], f"{label}[0]"), geometry.validate_positive(value[1], f"{label}[1]"))


def _colors(*groups) -> dict:
    return {name: color for group in groups for name, (color, _purpose) in group.items()}


def _put(plan: Plan, primitive: Primitive, colors: dict) -> Primitive:
    """Add primitive to plan, registering its layer (colour from `colors`) the first time it is used, so a
    layer nothing is drawn on is never created."""
    plan.layer(primitive.layer, colors.get(primitive.layer))
    return plan.add(primitive)


def _poly(layer, tag, points, *, closed=True, kind="2d") -> Primitive:
    return Primitive("polyline", layer, tag, points=tuple(points), closed=closed, polyline_kind=kind)


def _line(layer, tag, a, b) -> Primitive:
    return Primitive("line", layer, tag, points=(a, b))


# ======= staircase =======


def _direction(direction) -> str:
    key = str(direction).strip().upper() if isinstance(direction, str) else ""
    if key in ("UP", "DN", "DOWN"):
        return "UP" if key == "UP" else "DN"
    raise geometry.ValidationError(f"direction must be 'UP' or 'DN', got {direction!r}")


def check_staircase(start_point, riser_count, *, width=None, tread_depth=None, direction="UP",
                    rotation_degrees=90.0, landing_depth=None, handrails=True, text_height=None) -> dict:
    """Everything about a staircase request that can be checked without knowing the drawing's units."""
    return {
        "start": _xy(start_point, "start_point"),
        "risers": _count(riser_count, "riser_count", 2, MAX_RISERS),
        "label": _direction(direction),
        "angle": geometry.validate_number(rotation_degrees, "rotation_degrees"),
        "width": None if width is None else geometry.validate_positive(width, "width"),
        "tread_depth": None if tread_depth is None else geometry.validate_positive(tread_depth, "tread_depth"),
        "landing_depth": None if landing_depth is None else _non_negative(landing_depth, "landing_depth"),
        "handrails": _flag(handrails, "handrails"),
        "text_height": None if text_height is None else geometry.validate_positive(text_height, "text_height"),
    }


def plan_staircase(start_point, riser_count, drawing_code: int, factor: float = 1.0, *, width=None,
                   tread_depth=None, direction="UP", rotation_degrees=90.0, landing_depth=None,
                   handrails=True, text_height=None) -> Plan:
    """A straight flight in plan.

    The flight starts at start_point (the left end of its first riser line, looking along the run), runs
    towards rotation_degrees (0 = +X, 90 = +Y) and is `width` wide to the right of that direction. It has
    riser_count risers and so riser_count - 1 treads; the landing follows the last riser. The walking-line
    arrow always points along the flight, away from start_point; `direction` ('UP' or 'DN') is the label it
    carries. Treads, risers, landing, handrails, arrow and note go on their own layers."""
    a = check_staircase(start_point, riser_count, width=width, tread_depth=tread_depth, direction=direction,
                        rotation_degrees=rotation_degrees, landing_depth=landing_depth, handrails=handrails,
                        text_height=text_height)
    start, risers, label, angle, handrails = a["start"], a["risers"], a["label"], a["angle"], a["handrails"]
    std = sizes(drawing_code)
    wide = std["stair_width"] if a["width"] is None else a["width"] * factor
    going = std["tread_depth"] if a["tread_depth"] is None else a["tread_depth"] * factor
    landing = wide if a["landing_depth"] is None else a["landing_depth"] * factor
    note = units.annotation_scale(drawing_code, None if a["text_height"] is None else a["text_height"] * factor)
    h = note["text_height"]
    rail_w, rail_in = std["rail_width"], std["rail_inset"]
    if handrails and wide <= 2 * rail_in + rail_w:
        raise geometry.ValidationError(
            f"width {wide:g} is too narrow for two handrails (needs more than {2 * rail_in + rail_w:g} drawing "
            "units); pass handrails=false or a wider flight")

    treads = risers - 1
    run = treads * going
    frame = Frame(start, angle)

    def at(u, w):  # u along the flight, w across it to the right of the run direction
        return frame.pt(u, -w)

    def box(u0, w0, u1, w1):
        return (at(u0, w0), at(u1, w0), at(u1, w1), at(u0, w1))

    plan = Plan()
    colors = _colors(STAIR_LAYERS)

    def put(primitive):
        return _put(plan, primitive, colors)

    for k in range(1, treads + 1):
        u0 = (k - 1) * going
        put(_poly("A-FLOR-TRED", f"tread:{k}", box(u0, 0.0, u0 + going, wide)))
    for k in range(1, risers + 1):
        u = (k - 1) * going
        put(_line("A-FLOR-RISR", f"riser:{k}", at(u, 0.0), at(u, wide)))
    if landing > 0:
        put(_poly("A-FLOR-LAND", "landing", box(run, 0.0, run + landing, wide)))
    if handrails:
        put(_poly("A-FLOR-HRAL", "handrail:left", box(0.0, rail_in - rail_w / 2, run, rail_in + rail_w / 2)))
        put(_poly("A-FLOR-HRAL", "handrail:right",
                  box(0.0, wide - rail_in - rail_w / 2, run, wide - rail_in + rail_w / 2)))

    # Walking line: dot at the tail, line along the middle, open arrowhead at the far end.
    centre = wide / 2.0
    tail_u, head_u = (0.5 * going, run - 0.5 * going) if run >= 2 * going else (0.2 * run, 0.8 * run)
    head_len = min(h, 0.45 * (head_u - tail_u))
    head_half = min(0.5 * head_len, 0.2 * wide)
    put(_poly("A-ANNO-SYMB", "arrow:line", (at(tail_u, centre), at(head_u, centre)), closed=False))
    put(_poly("A-ANNO-SYMB", "arrow:head",
              (at(head_u - head_len, centre - head_half), at(head_u, centre),
               at(head_u - head_len, centre + head_half)), closed=False))
    put(Primitive("circle", "A-ANNO-SYMB", "arrow:tail", center=at(tail_u, centre),
                  radius=min(0.15 * h, 0.05 * wide)))
    text = f"{label} {risers}R"
    # The note sits beyond the first riser; keep its (horizontal) text clear of the flight at any rotation.
    half_w, half_h = 0.35 * h * len(text), 0.6 * h
    clearance = 0.5 * h + abs(math.cos(math.radians(angle))) * half_w + abs(math.sin(math.radians(angle))) * half_h
    put(Primitive("mtext", "A-ANNO-NOTE", "stair:note", text=text, location=at(-clearance, centre),
                  height=h, width=0.0, attach="middle_center"))

    plan.meta = {
        "staircase": {
            "direction": label, "riser_count": risers, "tread_count": treads, "tread_depth": going,
            "width": wide, "run_length": run, "landing_depth": landing, "overall_length": run + landing,
            "rotation_degrees": angle, "handrails": bool(handrails), "note": text,
            "start_point": list(start), "flight_end_point": list(at(run, centre)[:2]),
            "landing_end_point": list(at(run + landing, centre)[:2]),
            "walking_line": [list(at(tail_u, centre)[:2]), list(at(head_u, centre)[:2])],
            "corners": [list(p[:2]) for p in box(0.0, 0.0, run + landing, wide)],
        },
        "annotation": note,
        "drawing_unit": units.describe(drawing_code),
    }
    return plan


# ======= wall outlines and intersections =======


def outline_centerline(points, rel_tol: float = 1e-6) -> dict | None:
    """Centreline of a wall drawn as a closed rectangle (the 4-point outline autocad_draw_wall and the
    floor-plan generators produce): {start, end, thickness, length, angle}. None when the points are not
    a rectangle longer than it is thick."""
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) == 5 and pts[0] == pts[-1]:
        pts = pts[:4]
    if len(pts) != 4:
        return None
    edges = [(pts[(i + 1) % 4][0] - pts[i][0], pts[(i + 1) % 4][1] - pts[i][1]) for i in range(4)]
    side = [math.hypot(*e) for e in edges]
    if min(side) <= 0:
        return None
    tol = rel_tol * max(side)
    if (abs(side[0] - side[2]) > tol or abs(side[1] - side[3]) > tol
            or abs(edges[0][0] + edges[2][0]) > tol or abs(edges[0][1] + edges[2][1]) > tol
            or abs(edges[0][0] * edges[1][0] + edges[0][1] * edges[1][1]) > rel_tol * side[0] * side[1]):
        return None

    def mid(a, b):
        return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)

    if side[0] >= side[1]:
        start, end, thickness = mid(pts[0], pts[3]), mid(pts[1], pts[2]), side[1]
    else:
        start, end, thickness = mid(pts[0], pts[1]), mid(pts[3], pts[2]), side[0]
    length = math.dist(start, end)
    if length <= thickness * (1 + 1e-9):
        return None
    return {"start": start, "end": end, "thickness": thickness, "length": length,
            "angle": math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))}


def wall_segments(entities, layers=None) -> tuple:
    """(walls, ignored): the rectangular wall outlines among snapshot entities. layers lists exact layer
    names (case-insensitive); None takes every layer starting with A-WALL. Closed polylines on those
    layers that are not simple rectangles are counted in `ignored`."""
    wanted = {name.lower() for name in layers} if layers else None
    walls, ignored = [], 0
    for e in entities:
        if e.get("type") not in ("LWPOLYLINE", "POLYLINE3D", "POLYLINE") or not e.get("closed"):
            continue
        layer = e.get("layer") or "0"
        if not ((layer.lower() in wanted) if wanted else layer.upper().startswith("A-WALL")):
            continue
        centerline = outline_centerline(e.get("points") or [])
        if centerline is None:
            ignored += 1
            continue
        walls.append({**centerline, "handle": e.get("handle"), "layer": layer})
    if len(walls) > MAX_WALLS_SCANNED:
        raise geometry.ValidationError(f"{len(walls)} wall outlines found; at most {MAX_WALLS_SCANNED} are scanned")
    return walls, ignored


def _centerline_cross(a: dict, b: dict):
    """Where the two wall centrelines meet, if that point is on (or just beyond the end of, by half the
    other wall's thickness) both walls. Parallel walls -- including the pieces of one wall -- never meet."""
    la, lb = a["length"], b["length"]
    ua = ((a["end"][0] - a["start"][0]) / la, (a["end"][1] - a["start"][1]) / la)
    ub = ((b["end"][0] - b["start"][0]) / lb, (b["end"][1] - b["start"][1]) / lb)
    denominator = ua[0] * ub[1] - ua[1] * ub[0]
    if abs(denominator) < 1e-9:
        return None
    dx, dy = b["start"][0] - a["start"][0], b["start"][1] - a["start"][1]
    ta = (dx * ub[1] - dy * ub[0]) / denominator
    tb = (dx * ua[1] - dy * ua[0]) / denominator
    eps = 1e-6 * max(la, lb, 1.0)
    if (-b["thickness"] / 2 - eps <= ta <= la + b["thickness"] / 2 + eps
            and -a["thickness"] / 2 - eps <= tb <= lb + a["thickness"] / 2 + eps):
        return (a["start"][0] + ua[0] * ta, a["start"][1] + ua[1] * ta)
    return None


def _candidate_pairs(walls: list):
    """Index pairs (i < j) of walls whose footprint boxes, each grown by its thickness, overlap. A sweep along
    x finds them without comparing every wall with every other."""
    boxes = []
    for w in walls:
        reach = w["thickness"]
        boxes.append((min(w["start"][0], w["end"][0]) - reach, min(w["start"][1], w["end"][1]) - reach,
                      max(w["start"][0], w["end"][0]) + reach, max(w["start"][1], w["end"][1]) + reach))
    order = sorted(range(len(walls)), key=lambda i: boxes[i][0])
    for position, i in enumerate(order):
        for j in order[position + 1:]:
            if boxes[j][0] > boxes[i][2]:
                break
            if boxes[j][3] >= boxes[i][1] and boxes[j][1] <= boxes[i][3]:
                yield (i, j) if i < j else (j, i)


def _merge_junctions(found: list) -> list:
    """Group meeting points that lie closer together than half a wall thickness into one junction each."""
    if not found:
        return []
    cell = 0.5 * max(thickness for _, thickness, _ in found)  # no merge distance is larger than this
    clusters, grid = [], {}

    def cell_of(point):
        return (math.floor(point[0] / cell), math.floor(point[1] / cell))

    def nearby(point):
        cx, cy = cell_of(point)
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                yield from grid.get((gx, gy), ())

    for point, thickness, handles in found:
        for index in nearby(point):
            cluster = clusters[index]
            if math.dist(cluster["anchor"], point) <= 0.5 * min(cluster["thickness"], thickness):
                cluster["sum"] = (cluster["sum"][0] + point[0], cluster["sum"][1] + point[1])
                cluster["n"] += 1
                cluster["thickness"] = min(cluster["thickness"], thickness)
                cluster["handles"].update(handles)
                break
        else:
            grid.setdefault(cell_of(point), []).append(len(clusters))
            clusters.append({"anchor": point, "sum": point, "n": 1, "thickness": thickness, "handles": set(handles)})
    return [{"point": (c["sum"][0] / c["n"], c["sum"][1] / c["n"]), "walls": sorted(c["handles"])} for c in clusters]


def wall_intersections(walls: list) -> list:
    """One point for every place wall centrelines meet (corners, T and X junctions): {point, walls}.
    Meetings closer together than half a wall thickness are one junction."""
    found = []
    for i, j in sorted(_candidate_pairs(walls)):
        a, b = walls[i], walls[j]
        point = _centerline_cross(a, b)
        if point is not None:
            found.append((point, min(a["thickness"], b["thickness"]), [h for h in (a.get("handle"), b.get("handle")) if h]))
    return _merge_junctions(found)


# ======= column grid =======


def check_column_grid(*, x_spacings=None, y_spacings=None, origin=(0.0, 0.0), points=None, column_size=None,
                      rotation_degrees=0.0, layer="COLUMNS", labels=True, dimensions=True, text_height=None,
                      wall_intersections_wanted=False) -> dict:
    """Everything about a column-grid request that can be checked without knowing the drawing's units."""
    if (x_spacings is None) != (y_spacings is None):
        raise geometry.ValidationError("give both x_spacings and y_spacings for a grid, or neither")
    if x_spacings is None and not points and not wall_intersections_wanted:
        raise geometry.ValidationError(
            "no column positions: give x_spacings and y_spacings, points, or at_wall_intersections=true")
    return {
        "x_spacings": None if x_spacings is None else _bays(x_spacings, "x_spacings"),
        "y_spacings": None if y_spacings is None else _bays(y_spacings, "y_spacings"),
        "origin": _xy(origin if origin is not None else (0.0, 0.0), "origin"),
        "points": [_xy(point, f"points[{i}]") for i, point in enumerate(points or [])],
        "column_size": None if column_size is None else _pair(column_size, "column_size"),
        "rotation": geometry.validate_number(rotation_degrees, "rotation_degrees"),
        "layer": geometry.validate_layer_name(layer, "layer"),
        "labels": _flag(labels, "labels"),
        "dimensions": _flag(dimensions, "dimensions"),
        "text_height": None if text_height is None else geometry.validate_positive(text_height, "text_height"),
    }


def plan_column_grid(drawing_code: int, factor: float = 1.0, *, x_spacings=None, y_spacings=None,
                     origin=(0.0, 0.0), points=None, wall_points=None, column_size=None, rotation_degrees=0.0,
                     layer="COLUMNS", labels=True, dimensions=True, text_height=None) -> Plan:
    """Rectangular columns, each a closed outline plus a SOLID hatch on `layer`.

    Positions come from a grid (x_spacings left to right, y_spacings bottom to top, from origin), from custom
    `points` and from `wall_points` (already found by wall_intersections); a position given twice is drawn
    once. Marks C1, C2, ... run bottom to top, left to right. Spacings and column_size are multiplied by
    factor; origin, points and wall_points are drawing coordinates. Grid dimensions are added only for a grid."""
    a = check_column_grid(x_spacings=x_spacings, y_spacings=y_spacings, origin=origin, points=points,
                          column_size=column_size, rotation_degrees=rotation_degrees, layer=layer, labels=labels,
                          dimensions=dimensions, text_height=text_height,
                          wall_intersections_wanted=wall_points is not None)
    size = sizes(drawing_code)["column"] if a["column_size"] is None else tuple(v * factor for v in a["column_size"])
    rotation, layer, labels, dimensions = a["rotation"], a["layer"], a["labels"], a["dimensions"]
    note = units.annotation_scale(drawing_code, None if a["text_height"] is None else a["text_height"] * factor)
    h = note["text_height"]

    candidates = []  # (x, y, source, grid reference)
    grid = None
    if a["x_spacings"] is not None:
        ox, oy = a["origin"]
        xs = [ox]
        for bay in a["x_spacings"]:
            xs.append(xs[-1] + bay * factor)
        ys = [oy]
        for bay in a["y_spacings"]:
            ys.append(ys[-1] + bay * factor)
        rows = letters(len(ys))
        for j, y in enumerate(ys):
            for i, x in enumerate(xs):
                candidates.append((x, y, "grid", f"{rows[j]}{i + 1}"))
        grid = {"x_lines": xs, "y_lines": ys, "row_labels": rows}
    candidates += [(x, y, "custom", None) for x, y in a["points"]]
    candidates += [(float(x), float(y), "wall_intersection", None) for x, y in (wall_points or [])]
    if not candidates:
        raise geometry.ValidationError(
            "no column positions: the walls on the chosen layers have no intersections; add x_spacings and "
            "y_spacings or points")
    if len(candidates) > MAX_COLUMNS:
        raise geometry.ValidationError(f"{len(candidates)} column positions requested; at most {MAX_COLUMNS} per call")
    tolerance = 1e-6 * max(1.0, size[0], size[1])
    kept, skipped = [], 0
    for x, y, source, ref in candidates:
        if any(abs(x - k[0]) <= tolerance and abs(y - k[1]) <= tolerance for k in kept):
            skipped += 1
            continue
        kept.append((x, y, source, ref))
    kept.sort(key=lambda k: (round(k[1] / tolerance), round(k[0] / tolerance)))

    plan = Plan()
    text_layer, dim_layer = f"{layer}-TEXT", f"{layer}-DIM"
    colors = {layer: COLUMN_LAYERS["COLUMNS"][0], text_layer: COLUMN_LAYERS["COLUMNS-TEXT"][0],
              dim_layer: COLUMN_LAYERS["COLUMNS-DIM"][0]}

    def put(primitive):
        return _put(plan, primitive, colors)

    columns = []
    for index, (x, y, source, ref) in enumerate(kept, start=1):
        mark = f"C{index}"
        frame = Frame((x, y), rotation)
        outline = frame.rect(-size[0] / 2, -size[1] / 2, size[0] / 2, size[1] / 2)
        put(_poly(layer, f"column:{mark}", outline))
        put(Primitive("hatch", layer, f"column_fill:{mark}", points=outline, pattern="SOLID"))
        if labels:
            put(Primitive("text", text_layer, f"label:{mark}", text=mark, height=h,
                          location=(_r(x + size[0] / 2 + 0.3 * h), _r(y + size[1] / 2 + 0.3 * h), 0.0)))
        columns.append({"mark": mark, "center": [x, y], "size": list(size), "source": source, "grid_ref": ref})

    if dimensions and grid is not None:
        xs, ys = grid["x_lines"], grid["y_lines"]
        reach = max(size) / 2.0 + 4 * h  # clear of the column outlines

        def dim(tag, a, b, location, rotation_degrees):
            put(Primitive("dim_linear", dim_layer, tag, points=(a, b), location=location,
                          rotation=rotation_degrees, height=h))

        for i in range(len(xs) - 1):
            dim(f"dim:x:{i}", (xs[i], ys[0], 0.0), (xs[i + 1], ys[0], 0.0), (xs[i], ys[0] - reach, 0.0), 0.0)
        if len(xs) > 2:
            dim("dim:x:overall", (xs[0], ys[0], 0.0), (xs[-1], ys[0], 0.0), (xs[0], ys[0] - 2 * reach, 0.0), 0.0)
        for j in range(len(ys) - 1):
            dim(f"dim:y:{j}", (xs[0], ys[j], 0.0), (xs[0], ys[j + 1], 0.0), (xs[0] - reach, ys[j], 0.0), 90.0)
        if len(ys) > 2:
            dim("dim:y:overall", (xs[0], ys[0], 0.0), (xs[0], ys[-1], 0.0), (xs[0] - 2 * reach, ys[0], 0.0), 90.0)

    counts = {}
    for column in columns:
        counts[column["source"]] = counts.get(column["source"], 0) + 1
    plan.meta = {
        "columns": columns, "column_count": len(columns), "by_source": counts, "column_size": list(size),
        "rotation_degrees": rotation, "layer": layer, "duplicates_skipped": skipped, "grid": grid,
        "annotation": note, "drawing_unit": units.describe(drawing_code),
    }
    return plan


def _bays(values, label: str) -> list:
    if not isinstance(values, list) or not values:
        raise geometry.ValidationError(f"{label} must be a non-empty list of bay sizes")
    if len(values) > 100:
        raise geometry.ValidationError(f"{label} has more than 100 bays")
    return [geometry.validate_positive(v, f"{label}[{i}]") for i, v in enumerate(values)]


# ======= window in a wall =======


def window_type(tag) -> str:
    key = tag.strip().upper() if isinstance(tag, str) else ""
    if key not in WINDOW_TYPES:
        raise geometry.ValidationError(f"window_type must be one of {sorted(WINDOW_TYPES)}, got {tag!r}")
    return key


def check_wall_window(tag, *, offset=None, width=None, trim_wall=True, show_tag=True, tag_side="left",
                      text_height=None, window_layer="A-GLAZ") -> dict:
    """Everything about a window request that can be checked without knowing the drawing's units."""
    if tag_side not in ("left", "right"):
        raise geometry.ValidationError(f"tag_side must be 'left' or 'right', got {tag_side!r}")
    return {
        "kind": window_type(tag),
        "offset": None if offset is None else geometry.validate_number(offset, "offset"),
        "width": None if width is None else geometry.validate_positive(width, "width"),
        "trim_wall": _flag(trim_wall, "trim_wall"),
        "show_tag": _flag(show_tag, "show_tag"),
        "tag_side": tag_side,
        "text_height": None if text_height is None else geometry.validate_positive(text_height, "text_height"),
        "window_layer": geometry.validate_layer_name(window_layer, "layer"),
    }


def check_wall_points(start_point, end_point) -> tuple:
    """The two ends of a wall centreline as (x, y) pairs; they must differ."""
    start, end = _xy(start_point, "wall_start"), _xy(end_point, "wall_end")
    if math.dist(start, end) <= 0:
        raise geometry.ValidationError("wall_start and wall_end must differ")
    return start, end


def explicit_wall(start_point, end_point, thickness, drawing_code: int, factor: float = 1.0, layer=None) -> dict:
    """A straight wall given by its centreline (drawing coordinates, elevation ignored) and thickness (times
    factor; default: the standard exterior wall of the drawing's units)."""
    start, end = check_wall_points(start_point, end_point)
    length = math.dist(start, end)
    wide = (units.defaults_for(drawing_code)["exterior_wall"] if thickness is None
            else geometry.validate_positive(thickness, "thickness") * factor)
    if wide >= length:
        raise geometry.ValidationError(f"the wall is {length:g} long but {wide:g} thick; check thickness and unit")
    return {"start": start, "end": end, "thickness": wide, "length": length, "layer": layer, "handle": None,
            "angle": math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))}


def wall_from_entity(entity: dict) -> dict:
    """The wall that an existing closed-rectangle polyline (as drawn by autocad_draw_wall or the floor-plan
    generators) outlines, in the form plan_wall_window wants."""
    handle = entity.get("handle")
    if entity.get("type") not in ("LWPOLYLINE", "POLYLINE3D", "POLYLINE") or not entity.get("closed"):
        raise geometry.ValidationError(
            f"entity {handle} is a {entity.get('type')}; a wall must be a closed polyline outline")
    centerline = outline_centerline(entity.get("points") or [])
    if centerline is None:
        raise geometry.ValidationError(
            f"entity {handle} is not a straight wall outline: it must be a closed 4-point rectangle longer than "
            "it is thick, like the outlines autocad_draw_wall draws")
    return {**centerline, "layer": entity.get("layer"), "handle": handle}


def plan_wall_window(wall: dict, tag, drawing_code: int, factor: float = 1.0, *, offset=None, width=None,
                     trim_wall=True, show_tag=True, tag_side="left", text_height=None, window_layer="A-GLAZ",
                     wall_layer="A-WALL") -> Plan:
    """A window of type W1, W2 or W3 in a straight wall {start, end, thickness, length, angle[, layer, handle]}.

    The opening is `width` wide (default: the type's) and centred `offset` along the wall from its start
    (default: the middle). With trim_wall the wall is replaced by two pieces that stop at the opening;
    without it the wall is left alone and only the opening's jamb lines are drawn. The window itself is two
    glass-pane lines across the middle of the wall, a sill line on each wall face, and a mullion tick per
    sash division. The tag (W1...) sits beside the wall on `tag_side` ('left' or 'right' of start to end)."""
    a = check_wall_window(tag, offset=offset, width=width, trim_wall=trim_wall, show_tag=show_tag, tag_side=tag_side,
                          text_height=text_height, window_layer=window_layer)
    kind, trim_wall, show_tag, tag_side, window_layer = (a["kind"], a["trim_wall"], a["show_tag"], a["tag_side"],
                                                         a["window_layer"])
    std = sizes(drawing_code)
    spec_width, spec_height, spec_sill = std[kind]
    opening = spec_width if a["width"] is None else a["width"] * factor
    thickness, length = wall["thickness"], wall["length"]
    centre = length / 2.0 if a["offset"] is None else a["offset"] * factor
    s0, s1 = centre - opening / 2.0, centre + opening / 2.0
    eps = 1e-9 * max(length, 1.0)
    if opening >= length - eps:
        raise geometry.ValidationError(f"a window {opening:g} wide does not fit a wall {length:g} long")
    if s0 < -eps or s1 > length + eps:
        raise geometry.ValidationError(
            f"the window would run past the wall: for a window {opening:g} wide, offset must put its centre "
            f"between {opening / 2:g} and {length - opening / 2:g} along the wall (drawing units; the wall is "
            f"{length:g} long)")
    s0, s1 = max(s0, 0.0), min(s1, length)
    note = units.annotation_scale(drawing_code, None if a["text_height"] is None else a["text_height"] * factor)
    h = note["text_height"]
    sashes = WINDOW_TYPES[kind]["sashes"]
    half, pane = thickness / 2.0, thickness * 0.25 / 2.0
    frame = Frame(wall["start"], wall["angle"])
    layer_of_wall = wall.get("layer") or wall_layer

    plan = Plan()
    sill_layer, tag_layer = f"{window_layer}-SILL", f"{window_layer}-IDEN"
    standard = ARCHITECTURAL_LAYERS.get(layer_of_wall)
    colors = {window_layer: WINDOW_LAYERS["A-GLAZ"][0], sill_layer: WINDOW_LAYERS["A-GLAZ-SILL"][0],
              tag_layer: WINDOW_LAYERS["A-GLAZ-IDEN"][0],
              layer_of_wall: standard["color_index"] if standard else 7}

    def put(primitive):
        return _put(plan, primitive, colors)

    pieces = []
    if trim_wall:
        # Same corner order as geometry.wall_outline_points (start-left, end-left, end-right, start-right),
        # and the same 3D polyline kind, so takeoff and QC treat the pieces like any other wall.
        for name, u0, u1 in (("start", 0.0, s0), ("end", s1, length)):
            if u1 - u0 > eps:
                corners = (frame.pt(u0, half), frame.pt(u1, half), frame.pt(u1, -half), frame.pt(u0, -half))
                put(_poly(layer_of_wall, f"wall_piece:{name}", corners, kind="3d"))
                pieces.append({"name": name, "from": u0, "to": u1, "tag": f"wall_piece:{name}"})
    else:
        for name, u in (("start", s0), ("end", s1)):
            put(_line(window_layer, f"jamb:{name}", frame.pt(u, -half), frame.pt(u, half)))
    put(_line(sill_layer, "sill:left", frame.pt(s0, half), frame.pt(s1, half)))
    put(_line(sill_layer, "sill:right", frame.pt(s0, -half), frame.pt(s1, -half)))
    put(_line(window_layer, "glass:left", frame.pt(s0, pane), frame.pt(s1, pane)))
    put(_line(window_layer, "glass:right", frame.pt(s0, -pane), frame.pt(s1, -pane)))
    for k in range(1, sashes):
        u = s0 + k * (s1 - s0) / sashes
        put(_line(window_layer, f"mullion:{k}", frame.pt(u, -pane), frame.pt(u, pane)))
    if show_tag:
        side = 1.0 if tag_side == "left" else -1.0
        put(Primitive("mtext", tag_layer, "window:tag", text=kind,
                      location=frame.pt((s0 + s1) / 2.0, side * (half + 1.5 * h)), height=h, width=0.0,
                      attach="middle_center"))

    to_mm = units.convert(1.0, drawing_code, MM)
    plan.meta = {
        "window": {
            "type": kind, "name": WINDOW_TYPES[kind]["name"], "sashes": sashes, "mullions": sashes - 1,
            "width": s1 - s0, "height": spec_height, "sill_height": spec_sill, "head_height": spec_sill + spec_height,
            "size_mm": {"width": round((s1 - s0) * to_mm, 3), "height": round(spec_height * to_mm, 3),
                        "sill_height": round(spec_sill * to_mm, 3)},
            "offset": centre, "centre": list(frame.pt(centre)[:2]),
            "opening_start": list(frame.pt(s0)[:2]), "opening_end": list(frame.pt(s1)[:2]),
        },
        "wall": {"start": list(wall["start"]), "end": list(wall["end"]), "thickness": thickness, "length": length,
                 "layer": layer_of_wall, "handle": wall.get("handle"), "trimmed": bool(trim_wall), "pieces": pieces},
        "annotation": note,
        "drawing_unit": units.describe(drawing_code),
    }
    return plan


# ======= furniture and fixtures =======


class Sketch:
    """Furniture drawn in its own coordinates (+x to the right, +y towards the back wall), placed afterwards
    so the centre of its bounding box lands on the requested position."""

    def __init__(self):
        self.items = []
        self._stack = [(1.0, 0.0, 0.0, 0.0, 0.0)]  # cos, sin, tx, ty, rotation degrees

    @contextlib.contextmanager
    def at(self, x: float, y: float, rotation_degrees: float = 0.0):
        """Draw a sub-assembly (an armchair) rotated by rotation_degrees about, and moved to, (x, y)."""
        c0, s0, tx0, ty0, r0 = self._stack[-1]
        a = math.radians(rotation_degrees)
        c1, s1 = math.cos(a), math.sin(a)
        self._stack.append((c0 * c1 - s0 * s1, s0 * c1 + c0 * s1, tx0 + c0 * x - s0 * y, ty0 + s0 * x + c0 * y,
                            r0 + rotation_degrees))
        try:
            yield self
        finally:
            self._stack.pop()

    def _map(self, x, y):
        c, s, tx, ty, _ = self._stack[-1]
        return (tx + c * x - s * y, ty + s * x + c * y)

    def poly(self, tag, points, closed=True):
        self.items.append({"kind": "polyline", "tag": tag, "points": [self._map(*p) for p in points],
                           "closed": closed})

    def rect(self, tag, x0, y0, x1, y1):
        self.poly(tag, ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))

    def line(self, tag, a, b):
        self.items.append({"kind": "line", "tag": tag, "points": [self._map(*a), self._map(*b)]})

    def circle(self, tag, centre, radius):
        self.items.append({"kind": "circle", "tag": tag, "center": self._map(*centre), "radius": radius})

    def arc(self, tag, centre, radius, start_degrees, end_degrees):
        rotation = self._stack[-1][4]
        self.items.append({"kind": "arc", "tag": tag, "center": self._map(*centre), "radius": radius,
                           "start": start_degrees + rotation, "end": end_degrees + rotation})

    def bbox(self) -> tuple:
        xs, ys = [], []
        for item in self.items:
            if item["kind"] in ("polyline", "line"):
                xs += [p[0] for p in item["points"]]
                ys += [p[1] for p in item["points"]]
            else:
                cx, cy = item["center"]
                r = item["radius"]
                if item["kind"] == "circle":
                    xs += [cx - r, cx + r]
                    ys += [cy - r, cy + r]
                else:
                    start = item["start"] % 360.0
                    end = start + ((item["end"] - item["start"]) % 360.0 or 360.0)
                    angles = [start, end] + [q for q in range(0, 1080, 90) if start < q < end]
                    xs += [cx + r * math.cos(math.radians(a)) for a in angles]
                    ys += [cy + r * math.sin(math.radians(a)) for a in angles]
        return (min(xs), min(ys), max(xs), max(ys))

    def place(self, plan: Plan, frame: Frame, layer: str) -> tuple:
        """Add every item to plan, centred on frame's origin; returns the (width, depth) of the footprint."""
        x0, y0, x1, y1 = self.bbox()
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0

        def world(p):
            return frame.pt(p[0] - cx, p[1] - cy)

        colors = {layer: FURNITURE_LAYERS["A-FURN"][0]}
        for item in self.items:
            if item["kind"] == "polyline":
                primitive = _poly(layer, item["tag"], [world(p) for p in item["points"]], closed=item["closed"])
            elif item["kind"] == "line":
                primitive = _line(layer, item["tag"], world(item["points"][0]), world(item["points"][1]))
            elif item["kind"] == "circle":
                primitive = Primitive("circle", layer, item["tag"], center=world(item["center"]),
                                      radius=item["radius"])
            else:
                primitive = Primitive("arc", layer, item["tag"], center=world(item["center"]), radius=item["radius"],
                                      start_angle=(item["start"] + frame.angle) % 360.0,
                                      end_angle=(item["end"] + frame.angle) % 360.0)
            _put(plan, primitive, colors)
        return (x1 - x0, y1 - y0)


def _bed(sk: Sketch, sz: dict, width, depth, variant, seats, return_length):
    base_w, base_d = sz[f"bed_{variant}"]
    w, d = (base_w if width is None else width), (base_d if depth is None else depth)
    headboard, margin, gap = sz["bed_headboard"], sz["bed_margin"], sz["bed_pillow_gap"]
    pillow_w, pillow_d = sz["bed_pillow"]
    count = 1 if variant == "single" else 2
    pillow_w = min(pillow_w, w / count - 2 * margin)
    if pillow_w <= 0 or d < 2 * (headboard + gap + pillow_d):
        raise geometry.ValidationError(f"a bed {w:g} x {d:g} is too small for its headboard and pillows")
    sk.rect("bed:mattress", 0.0, 0.0, w, d)
    sk.rect("bed:headboard", 0.0, d - headboard, w, d)
    top = d - headboard - gap
    for i in range(count):
        cx = w * (i + 0.5) / count
        sk.rect(f"bed:pillow:{i}", cx - pillow_w / 2, top - pillow_d, cx + pillow_w / 2, top)
    sk.line("bed:fold", (margin, 0.45 * d), (w - margin, 0.45 * d))
    return {"variant": variant, "pillows": count}


def _dining_table(sk: Sketch, sz: dict, width, depth, variant, seats, return_length):
    per_side = seats // 2
    chair, tuck, back = sz["dining_chair"], sz["dining_tuck"], sz["dining_chair_back"]
    length = width if width is not None else max(sz["dining_table_min"], per_side * sz["dining_pitch"])
    table_d = depth if depth is not None else sz["dining_table_depth"]
    pitch = length / per_side
    if chair > pitch:
        raise geometry.ValidationError(
            f"a table {length:g} long is too short for {seats} seats: each chair needs {chair:g} along the table")
    out = chair - tuck  # how far a chair sticks out past the table edge
    sk.rect("dining:table", 0.0, out, length, out + table_d)
    for i in range(per_side):
        cx = (i + 0.5) * pitch
        sk.rect(f"dining:chair:south:{i}", cx - chair / 2, 0.0, cx + chair / 2, chair)
        sk.rect(f"dining:chair_back:south:{i}", cx - chair / 2, 0.0, cx + chair / 2, back)
        top = out + table_d + out
        sk.rect(f"dining:chair:north:{i}", cx - chair / 2, top - chair, cx + chair / 2, top)
        sk.rect(f"dining:chair_back:north:{i}", cx - chair / 2, top - back, cx + chair / 2, top)
    return {"variant": None, "seats": seats, "chairs": 2 * per_side}


def _armchair(sk: Sketch, tag: str, size: float):
    back, arm = 0.22 * size, 0.16 * size
    sk.rect(f"{tag}:frame", -size / 2, -size / 2, size / 2, size / 2)
    sk.rect(f"{tag}:back", -size / 2, size / 2 - back, size / 2, size / 2)
    sk.rect(f"{tag}:arm:left", -size / 2, -size / 2, -size / 2 + arm, size / 2 - back)
    sk.rect(f"{tag}:arm:right", size / 2 - arm, -size / 2, size / 2, size / 2 - back)
    sk.rect(f"{tag}:seat", -size / 2 + arm, -size / 2, size / 2 - arm, size / 2 - back)


def _sofa_set(sk: Sketch, sz: dict, width, depth, variant, seats, return_length):
    arm, back = sz["sofa_arm"], sz["sofa_back"]
    sofa_d = depth if depth is not None else sz["sofa_depth"]
    sofa_w = width if width is not None else seats * sz["sofa_seat_pitch"] + 2 * arm
    if sofa_w <= 2 * arm or sofa_d <= back:
        raise geometry.ValidationError(f"a sofa {sofa_w:g} x {sofa_d:g} is too small for its arms and back")
    seat_w = (sofa_w - 2 * arm) / seats
    # The sofa's back edge is at y = 0; everything else sits in front of it (negative y).
    sk.rect("sofa:frame", -sofa_w / 2, -sofa_d, sofa_w / 2, 0.0)
    sk.rect("sofa:back", -sofa_w / 2, -back, sofa_w / 2, 0.0)
    sk.rect("sofa:arm:left", -sofa_w / 2, -sofa_d, -sofa_w / 2 + arm, -back)
    sk.rect("sofa:arm:right", sofa_w / 2 - arm, -sofa_d, sofa_w / 2, -back)
    for i in range(seats):
        x0 = -sofa_w / 2 + arm + i * seat_w
        sk.rect(f"sofa:seat:{i}", x0, -sofa_d, x0 + seat_w, -back)
    table_w, table_d = sz["sofa_coffee"]
    table_w = min(table_w, 0.6 * sofa_w)
    table_top = -sofa_d - sz["sofa_gap"]
    sk.rect("sofa:coffee_table", -table_w / 2, table_top - table_d, table_w / 2, table_top)
    chair = sz["sofa_armchair"]
    chair_y = table_top - table_d / 2
    chair_x = table_w / 2 + sz["sofa_side_gap"] + chair / 2
    with sk.at(-chair_x, chair_y, 90.0):  # back to the left, facing the table
        _armchair(sk, "sofa:armchair:left", chair)
    with sk.at(chair_x, chair_y, -90.0):
        _armchair(sk, "sofa:armchair:right", chair)
    return {"variant": None, "seats": seats, "armchairs": 2}


def _wc(sk: Sketch, sz: dict, width, depth, variant, seats, return_length):
    bowl_w = width if width is not None else sz["wc_width"]
    total_d = depth if depth is not None else sz["wc_depth"]
    radius = bowl_w / 2.0
    tank_d, tank_w = 0.26 * total_d, 1.25 * bowl_w
    top = total_d - tank_d  # where the bowl meets the cistern
    if top - radius <= 0:
        raise geometry.ValidationError(f"a WC {bowl_w:g} wide is too shallow at {total_d:g} deep")
    sk.rect("wc:tank", -tank_w / 2, top, tank_w / 2, total_d)
    sk.line("wc:bowl:left", (-radius, radius), (-radius, top))
    sk.line("wc:bowl:right", (radius, radius), (radius, top))
    sk.arc("wc:bowl:front", (0.0, radius), radius, 180.0, 360.0)
    inner, seat_top = 0.78 * radius, top - 0.15 * radius
    sk.line("wc:seat:left", (-inner, radius), (-inner, seat_top))
    sk.line("wc:seat:right", (inner, radius), (inner, seat_top))
    sk.arc("wc:seat:front", (0.0, radius), inner, 180.0, 360.0)
    sk.line("wc:seat:back", (-inner, seat_top), (inner, seat_top))
    return {"variant": None}


def _kitchen_countertop(sk: Sketch, sz: dict, width, depth, variant, seats, return_length):
    length = width if width is not None else sz["kitchen_length"]
    counter_d = depth if depth is not None else sz["kitchen_depth"]
    leg = return_length if return_length is not None else sz["kitchen_return"]
    # The back edge (against the wall) is y = 0; the counter reaches forward to negative y.
    if variant == "straight":
        outline = [(0, 0), (length, 0), (length, -counter_d), (0, -counter_d)]
        run0, run1 = 0.0, length
    else:
        if leg <= counter_d or length <= counter_d:
            raise geometry.ValidationError(
                f"an L-shaped counter needs its return ({leg:g}) and run ({length:g}) longer than its depth ({counter_d:g})")
        if variant == "l_left":
            outline = [(0, 0), (length, 0), (length, -counter_d), (counter_d, -counter_d), (counter_d, -leg), (0, -leg)]
            run0, run1 = counter_d, length
        else:
            outline = [(0, 0), (length, 0), (length, -leg), (length - counter_d, -leg),
                       (length - counter_d, -counter_d), (0, -counter_d)]
            run0, run1 = 0.0, length - counter_d
    sk.poly("kitchen:counter", outline)
    sink_w, sink_d = sz["kitchen_sink"]
    hob_w, hob_d = sz["kitchen_hob"]
    free = (run1 - run0) - sink_w - hob_w
    if free <= 0 or sink_d >= counter_d or hob_d >= counter_d:
        raise geometry.ValidationError(
            f"the counter run ({run1 - run0:g} x {counter_d:g}) is too small for a sink and a hob; make it longer or deeper")
    gap = free / 3.0
    sink_x = run0 + gap + sink_w / 2.0
    hob_x = run0 + 2 * gap + sink_w + hob_w / 2.0
    mid_y = -counter_d / 2.0
    sk.rect("kitchen:sink", sink_x - sink_w / 2, mid_y - sink_d / 2, sink_x + sink_w / 2, mid_y + sink_d / 2)
    bowl_w, margin = (sink_w - 0.15 * sink_w) / 2.0, 0.05 * sink_w
    for i, x0 in enumerate((sink_x - sink_w / 2 + margin, sink_x + margin / 2)):
        sk.rect(f"kitchen:sink:bowl:{i}", x0, mid_y - sink_d / 2 + margin, x0 + bowl_w, mid_y + sink_d / 2 - margin)
    sk.circle("kitchen:tap", (sink_x, (mid_y + sink_d / 2) / 2.0), 0.035 * sink_w)
    sk.rect("kitchen:hob", hob_x - hob_w / 2, mid_y - hob_d / 2, hob_x + hob_w / 2, mid_y + hob_d / 2)
    dx, dy = 0.23 * hob_w, 0.23 * hob_d
    for i, (sx, sy, r) in enumerate(((-1, 1, 0.15), (1, 1, 0.11), (-1, -1, 0.11), (1, -1, 0.15))):
        sk.circle(f"kitchen:burner:{i}", (hob_x + sx * dx, mid_y + sy * dy), r * hob_w)
    return {"variant": variant}


_BUILDERS = {"bed": _bed, "dining_table": _dining_table, "sofa_set": _sofa_set, "wc": _wc,
             "kitchen_countertop": _kitchen_countertop}


def furniture_type(kind) -> str:
    key = kind.strip().lower().replace("-", "_").replace(" ", "_") if isinstance(kind, str) else ""
    if key not in FURNITURE_TYPES:
        raise geometry.ValidationError(f"block_type must be one of {sorted(FURNITURE_TYPES)}, got {kind!r}")
    return key


def check_furniture(kind, position, *, rotation_degrees=0.0, variant=None, width=None, depth=None, seats=None,
                    return_length=None, label=False, text_height=None, layer="A-FURN") -> dict:
    """Everything about a furniture request that can be checked without knowing the drawing's units."""
    kind = furniture_type(kind)
    spec = FURNITURE_TYPES[kind]
    if variant is None:
        variant = spec["default_variant"]
    elif not spec["variants"]:
        raise geometry.ValidationError(f"{kind} has no variants; leave variant empty")
    elif not isinstance(variant, str) or variant.strip().lower() not in spec["variants"]:
        raise geometry.ValidationError(f"variant for {kind} must be one of {list(spec['variants'])}, got {variant!r}")
    else:
        variant = variant.strip().lower()
    if kind == "dining_table":
        seats = 4 if seats is None else _count(seats, "seats", 2, 12)
        if seats % 2:
            raise geometry.ValidationError(f"seats must be even (chairs sit on both long sides), got {seats}")
    elif kind == "sofa_set":
        seats = 3 if seats is None else _count(seats, "seats", 2, 4)
    elif seats is not None:
        raise geometry.ValidationError(f"seats applies only to dining_table and sofa_set, not {kind}")
    if return_length is not None and not (kind == "kitchen_countertop" and variant != "straight"):
        raise geometry.ValidationError("return_length applies only to an L-shaped kitchen_countertop")
    return {
        "kind": kind, "variant": variant, "seats": seats,
        "centre": _xy(position, "position"),
        "rotation": geometry.validate_number(rotation_degrees, "rotation_degrees"),
        "width": None if width is None else geometry.validate_positive(width, "width"),
        "depth": None if depth is None else geometry.validate_positive(depth, "depth"),
        "return_length": None if return_length is None else geometry.validate_positive(return_length, "return_length"),
        "label": _flag(label, "label"),
        "text_height": None if text_height is None else geometry.validate_positive(text_height, "text_height"),
        "layer": geometry.validate_layer_name(layer, "layer"),
    }


def plan_furniture(kind, position, drawing_code: int, factor: float = 1.0, *, rotation_degrees=0.0, variant=None,
                   width=None, depth=None, seats=None, return_length=None, label=False, text_height=None,
                   layer="A-FURN") -> Plan:
    """A furniture or sanitary symbol drawn from lines, polylines, arcs and circles on `layer`.

    The symbol is centred on `position` (the middle of its footprint) and rotated counterclockwise about it;
    at rotation 0 its back (headboard, sofa back, cistern, counter edge against the wall) is towards +Y.
    width and depth override the default size: bed width across and depth head to foot, dining table length
    and width, sofa set the sofa's length and depth, WC bowl width and overall depth, kitchen counter run
    length and depth."""
    a = check_furniture(kind, position, rotation_degrees=rotation_degrees, variant=variant, width=width, depth=depth,
                        seats=seats, return_length=return_length, label=label, text_height=text_height, layer=layer)
    kind, variant, seats, centre, rotation, layer = (a["kind"], a["variant"], a["seats"], a["centre"], a["rotation"],
                                                    a["layer"])
    spec = FURNITURE_TYPES[kind]
    note = units.annotation_scale(drawing_code, None if a["text_height"] is None else a["text_height"] * factor)
    sz = sizes(drawing_code)
    width = None if a["width"] is None else a["width"] * factor
    depth = None if a["depth"] is None else a["depth"] * factor
    return_length = None if a["return_length"] is None else a["return_length"] * factor
    label = a["label"]

    sketch = Sketch()
    detail = _BUILDERS[kind](sketch, sz, width, depth, variant, seats, return_length)
    plan = Plan()
    frame = Frame(centre, rotation)
    footprint_w, footprint_d = sketch.place(plan, frame, layer)
    if label:
        text_layer = f"{layer}-TEXT"
        _put(plan, Primitive("mtext", text_layer, "furniture:label", text=spec["label"],
                             location=frame.pt(0.0, -(footprint_d / 2.0 + 1.2 * note["text_height"])),
                             height=note["text_height"], width=0.0, attach="middle_center"),
             {text_layer: FURNITURE_LAYERS["A-FURN-TEXT"][0]})
    plan.meta = {
        "furniture": {
            "block_type": kind, **detail, "position": list(centre), "rotation_degrees": rotation,
            "footprint": {"width": footprint_w, "depth": footprint_d,
                          "corners": [list(p[:2]) for p in frame.rect(-footprint_w / 2, -footprint_d / 2,
                                                                      footprint_w / 2, footprint_d / 2)]},
            "layer": layer,
        },
        "annotation": note,
        "drawing_unit": units.describe(drawing_code),
    }
    return plan
