"""Pure architecture logic: plan primitives, residential floor plans, structural
grids, stairs and sheets. No pywin32, no ezdxf.
"""

import math
from collections import Counter, deque
from dataclasses import dataclass, field

from domain import units
from utils import geometry


# ======= plan.py =======

PRIMITIVE_KINDS = ("line", "polyline", "arc", "circle", "text", "mtext", "dim_aligned", "dim_linear", "hatch")


@dataclass
class Primitive:
    kind: str
    layer: str
    tag: str
    points: tuple = ()  # line: (p1, p2); polyline: vertices; hatch: boundary; dims: (p1, p2)
    closed: bool = False
    polyline_kind: str = "3d"  # "3d" = AcDb3dPolyline / POLYLINE (V0.2.x walls) or "2d" = LWPOLYLINE
    center: tuple | None = None
    radius: float | None = None
    start_angle: float | None = None  # degrees, counterclockwise from +X
    end_angle: float | None = None
    text: str | None = None
    height: float | None = None
    width: float = 0.0
    rotation: float = 0.0  # degrees
    location: tuple | None = None  # text insertion / dimension-line point
    attach: str = "top_left"  # mtext attachment: top_left | middle_center
    pattern: str | None = None
    scale: float = 1.0

    def __post_init__(self):
        if self.kind not in PRIMITIVE_KINDS:
            raise ValueError(f"unknown primitive kind {self.kind!r}")

    def extent_points(self) -> list:
        if self.kind in ("arc", "circle"):
            cx, cy = self.center[0], self.center[1]
            r = self.radius
            return [(cx - r, cy - r), (cx + r, cy + r)]
        if self.kind in ("text", "mtext"):
            return [self.location[:2]]
        pts = [p[:2] for p in self.points]
        if self.location is not None:
            pts.append(self.location[:2])
        return pts

    def describe(self) -> dict:
        out = {"kind": self.kind, "layer": self.layer, "tag": self.tag}
        if self.points:
            out["points"] = [list(map(lambda v: round(v, 6), p)) for p in self.points]
        if self.closed:
            out["closed"] = True
        if self.center is not None:
            out.update(center=list(self.center), radius=self.radius)
        if self.start_angle is not None:
            out.update(start_angle=self.start_angle, end_angle=self.end_angle)
        if self.text is not None:
            out.update(text=self.text, height=self.height)
        if self.location is not None:
            out["location"] = list(self.location)
        if self.pattern:
            out["pattern"] = self.pattern
        return out


@dataclass
class Plan:
    """layers: name -> {"color": ACI or None, "linetype": name or None,
    "force": True to overwrite an existing layer's color (V0.2.3 floor plan
    behaviour), False to leave an existing layer's settings alone}."""

    layers: dict = field(default_factory=dict)
    primitives: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def add(self, primitive: Primitive) -> Primitive:
        self.primitives.append(primitive)
        return primitive

    def layer(self, name: str, color: int | None = None, linetype: str | None = None, force: bool = False):
        self.layers.setdefault(name, {"color": color, "linetype": linetype, "force": force})

    def bbox(self):
        pts = [p for prim in self.primitives for p in prim.extent_points()]
        if not pts:
            return None
        return [[min(p[0] for p in pts), min(p[1] for p in pts)], [max(p[0] for p in pts), max(p[1] for p in pts)]]

    def summary(self, max_primitives: int = 200) -> dict:
        return {
            "primitive_count": len(self.primitives),
            "counts_by_kind": dict(Counter(p.kind for p in self.primitives)),
            "counts_by_layer": dict(Counter(p.layer for p in self.primitives)),
            "layers": self.layers,
            "bbox": self.bbox(),
            "primitives": [p.describe() for p in self.primitives[:max_primitives]],
            "primitives_truncated": len(self.primitives) > max_primitives,
        }


def rect_points(x0, y0, x1, y1, z=0.0):
    return ((x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z))


def polar(origin, angle_deg, distance):
    a = math.radians(angle_deg)
    return (origin[0] + distance * math.cos(a), origin[1] + distance * math.sin(a), origin[2] if len(origin) > 2 else 0.0)


# ======= floorplan.py =======


# ======= shared symbols =======

DOOR_LEAF_THICKNESS_IN = 1.75  # solid-core door leaf, inches (V0.2.3 symbol constant)
DOOR_FRAME_DEPTH_IN = 4.5  # jamb tick length, inches (V0.2.3 symbol constant)


def door_symbol(plan: Plan, hinge, width: float, angle_deg: float, tag: str, layer: str = "A-DOOR",
                leaf_thickness: float = DOOR_LEAF_THICKNESS_IN, frame_depth: float = DOOR_FRAME_DEPTH_IN) -> dict:
    """V0.2.3 add_door_symbol geometry: a jamb tick at each edge of the
    opening, the leaf drawn open at 90 degrees, and a quarter-circle swing
    arc. angle_deg is the wall direction (0 = +X); the leaf opens towards
    angle_deg + 90."""
    wall_rad = math.radians(angle_deg)
    swing_rad = math.radians(angle_deg + 90.0)
    wall_dir = (math.cos(wall_rad), math.sin(wall_rad))
    swing_dir = (math.cos(swing_rad), math.sin(swing_rad))
    z = hinge[2]
    latch = (hinge[0] + width * wall_dir[0], hinge[1] + width * wall_dir[1], z)
    leaf_end = (hinge[0] + width * swing_dir[0], hinge[1] + width * swing_dir[1], z)
    half = frame_depth / 2.0
    for label, jamb in (("hinge_jamb", hinge), ("latch_jamb", latch)):
        p1 = (jamb[0] - half * swing_dir[0], jamb[1] - half * swing_dir[1], z)
        p2 = (jamb[0] + half * swing_dir[0], jamb[1] + half * swing_dir[1], z)
        plan.add(Primitive("line", layer, f"{tag}:{label}", points=(p1, p2)))
    plan.add(Primitive("polyline", layer, f"{tag}:leaf", closed=True,
                       points=tuple(geometry.wall_outline_points(hinge, leaf_end, leaf_thickness))))
    plan.add(Primitive("arc", layer, f"{tag}:arc", center=hinge, radius=width,
                       start_angle=math.degrees(wall_rad), end_angle=math.degrees(swing_rad)))
    return {"hinge_point": hinge, "latch_point": latch, "leaf_end": leaf_end, "width": width, "angle_deg": angle_deg}


def window_symbol(plan: Plan, start, length: float, wall_thickness: float, angle_deg: float, tag: str,
                  layer: str = "A-GLAZ") -> dict:
    """V0.2.3 add_window_symbol geometry: 3 parallel glazing lines across
    the wall thickness, `length` long, from start along angle_deg."""
    wall_rad = math.radians(angle_deg)
    wall_dir = (math.cos(wall_rad), math.sin(wall_rad))
    perp = (-wall_dir[1], wall_dir[0])
    z = start[2]
    for i, offset in enumerate((-wall_thickness / 2.0, 0.0, wall_thickness / 2.0)):
        p1 = (start[0] + perp[0] * offset, start[1] + perp[1] * offset, z)
        p2 = (p1[0] + wall_dir[0] * length, p1[1] + wall_dir[1] * length, z)
        plan.add(Primitive("line", layer, f"{tag}:line{i}", points=(p1, p2)))
    end = (start[0] + wall_dir[0] * length, start[1] + wall_dir[1] * length, z)
    return {"start_point": start, "end_point": end, "length": length, "wall_thickness": wall_thickness,
            "angle_deg": angle_deg}


def scale_plan(plan: Plan, factor: float) -> Plan:
    """Scale every length in plan about the origin (unit conversion)."""
    if factor == 1.0:
        return plan

    def s(p):
        return tuple(c * factor for c in p) if p is not None else None

    for prim in plan.primitives:
        prim.points = tuple(s(p) for p in prim.points)
        prim.center = s(prim.center)
        prim.location = s(prim.location)
        if prim.radius is not None:
            prim.radius *= factor
        if prim.height is not None:
            prim.height *= factor
        prim.width *= factor
        prim.scale *= factor
    return plan


# ======= V0.2.3 grid planner =======

EXTERIOR_WALL_THICKNESS = 9.0
INTERIOR_WALL_THICKNESS = 4.5
MAIN_DOOR_WIDTH = 36.0
INTERIOR_DOOR_WIDTH = 30.0
WINDOW_LENGTH = 48.0
ROOM_LABEL_HEIGHT = 6.0
GRID_COLS = 2
GRID_ROWS = 3
MIN_GRID_SPAN_INCHES = 180.0  # 15 ft
FLOOR_PLAN_LAYERS = {
    "A-WALL-EXT": 3, "A-WALL-INT": 2, "A-DOOR": 1, "A-GLAZ": 4, "A-TEXT": 7, "A-DIM": 6,
}
DEFAULT_ROOMS_CONFIG = [
    {"name": "Living Room", "col": 0, "row": 0, "col_span": 2, "row_span": 1},
    {"name": "Kitchen", "col": 0, "row": 1, "col_span": 1, "row_span": 1},
    {"name": "Bath", "col": 1, "row": 1, "col_span": 1, "row_span": 1},
    {"name": "Bedroom 1", "col": 0, "row": 2, "col_span": 1, "row_span": 1},
    {"name": "Bedroom 2", "col": 1, "row": 2, "col_span": 1, "row_span": 1},
]


def validate_rooms_config(rooms_config) -> list[dict]:
    if rooms_config is None:
        return [dict(room) for room in DEFAULT_ROOMS_CONFIG]
    if not isinstance(rooms_config, list) or not rooms_config:
        raise geometry.ValidationError("rooms_config must be a non-empty list of room dicts")
    validated = []
    for i, room in enumerate(rooms_config):
        if not isinstance(room, dict):
            raise geometry.ValidationError(f"rooms_config[{i}] must be a dict, got {type(room).__name__}")
        name = room.get("name")
        if not isinstance(name, str) or not name.strip():
            raise geometry.ValidationError(f"rooms_config[{i}].name must be a non-empty string")
        spec = {}
        for field, default in (("col", 0), ("row", 0), ("col_span", 1), ("row_span", 1)):
            value = room.get(field, default)
            if isinstance(value, bool) or not isinstance(value, int):
                raise geometry.ValidationError(f"rooms_config[{i}].{field} must be an int, got {value!r}")
            spec[field] = value
        if spec["col"] < 0 or spec["row"] < 0 or spec["col_span"] < 1 or spec["row_span"] < 1:
            raise geometry.ValidationError(f"rooms_config[{i}] ({name!r}) has an invalid col/row/span value")
        validated.append({"name": name, **spec})
    return validated


def build_room_grid(rooms: list[dict]) -> list[list[str | None]]:
    grid: list[list[str | None]] = [[None] * GRID_COLS for _ in range(GRID_ROWS)]
    for room in rooms:
        if room["col"] + room["col_span"] > GRID_COLS or room["row"] + room["row_span"] > GRID_ROWS:
            raise geometry.ValidationError(f"room {room['name']!r} does not fit in the {GRID_COLS}x{GRID_ROWS} room grid")
        for r in range(room["row"], room["row"] + room["row_span"]):
            for c in range(room["col"], room["col"] + room["col_span"]):
                if grid[r][c] is not None:
                    raise geometry.ValidationError(
                        f"room {room['name']!r} overlaps {grid[r][c]!r} at grid cell (col={c}, row={r})")
                grid[r][c] = room["name"]
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            if grid[r][c] is None:
                raise geometry.ValidationError(f"grid cell (col={c}, row={r}) is not covered by any room in rooms_config")
    return grid


def plan_grid_floor_plan(width_ft: float, length_ft: float, rooms_config=None) -> Plan:
    """The V0.2.3 macro as a Plan, in inches. meta keeps what the result needs."""
    width_ft = geometry.validate_positive(width_ft, "width_ft")
    length_ft = geometry.validate_positive(length_ft, "length_ft")
    rooms = validate_rooms_config(rooms_config)
    grid = build_room_grid(rooms)
    width_in, length_in = width_ft * 12.0, length_ft * 12.0
    if width_in < MIN_GRID_SPAN_INCHES or length_in < MIN_GRID_SPAN_INCHES:
        raise geometry.ValidationError(
            f"width_ft/length_ft too small: footprint must be at least {MIN_GRID_SPAN_INCHES / 12.0:g} ft "
            f"on each side for a {GRID_COLS}x{GRID_ROWS} room grid")

    plan = Plan()
    for name, color in FLOOR_PLAN_LAYERS.items():
        plan.layer(name, color, force=True)  # V0.2.3 set these colors on every run

    ix0 = iy0 = EXTERIOR_WALL_THICKNESS / 2.0
    ix1, iy1 = width_in - EXTERIOR_WALL_THICKNESS / 2.0, length_in - EXTERIOR_WALL_THICKNESS / 2.0
    cell_w, cell_h = (ix1 - ix0) / GRID_COLS, (iy1 - iy0) / GRID_ROWS

    def cell_rect(col, row, col_span, row_span):
        return ix0 + col * cell_w, iy0 + row * cell_h, ix0 + (col + col_span) * cell_w, iy0 + (row + row_span) * cell_h

    outline = [(0.0, 0.0, 0.0), (width_in, 0.0, 0.0), (width_in, length_in, 0.0), (0.0, length_in, 0.0)]
    for i in range(4):
        seg = geometry.wall_outline_points(outline[i], outline[(i + 1) % 4], EXTERIOR_WALL_THICKNESS)
        plan.add(Primitive("polyline", "A-WALL-EXT", f"ext_wall:{i}", points=tuple(seg), closed=True))

    interior = 0
    for c in range(1, GRID_COLS):
        x = ix0 + c * cell_w
        for r in range(GRID_ROWS):
            if grid[r][c - 1] != grid[r][c]:
                seg = geometry.wall_outline_points((x, iy0 + r * cell_h, 0.0), (x, iy0 + (r + 1) * cell_h, 0.0),
                                                   INTERIOR_WALL_THICKNESS)
                plan.add(Primitive("polyline", "A-WALL-INT", f"int_wall:{interior}", points=tuple(seg), closed=True))
                interior += 1
    for r in range(1, GRID_ROWS):
        y = iy0 + r * cell_h
        for c in range(GRID_COLS):
            if grid[r - 1][c] != grid[r][c]:
                seg = geometry.wall_outline_points((ix0 + c * cell_w, y, 0.0), (ix0 + (c + 1) * cell_w, y, 0.0),
                                                   INTERIOR_WALL_THICKNESS)
                plan.add(Primitive("polyline", "A-WALL-INT", f"int_wall:{interior}", points=tuple(seg), closed=True))
                interior += 1

    room_rows, room_rects = [], {}
    for idx, room in enumerate(rooms):
        x0, y0, x1, y1 = cell_rect(room["col"], room["row"], room["col_span"], room["row_span"])
        room_rects[room["name"]] = (x0, y0, x1, y1)
        center = ((x0 + x1) / 2.0, (y0 + y1) / 2.0, 0.0)
        box_width = max(x1 - x0 - 4.0, ROOM_LABEL_HEIGHT * 2.0)
        plan.add(Primitive("mtext", "A-TEXT", f"room_label:{idx}", text=room["name"], location=center,
                           width=box_width, height=ROOM_LABEL_HEIGHT))
        room_rows.append({"name": room["name"], "bounds": [x0, y0, x1, y1], "label_tag": f"room_label:{idx}"})

    entry_room = grid[0][GRID_COLS // 2]
    entry_hinge = (width_in / 2.0 - MAIN_DOOR_WIDTH / 2.0, 0.0, 0.0)
    doors = [{"room": entry_room, "kind": "main", "tag": "door:0",
              **door_symbol(plan, entry_hinge, MAIN_DOOR_WIDTH, 0.0, "door:0")}]

    placed_doors, used = {entry_room}, set()
    for room in rooms:
        if room["name"] in placed_doors:
            continue
        placed = False
        for r in range(room["row"], room["row"] + room["row_span"]):
            if placed:
                break
            for c in range(room["col"], room["col"] + room["col_span"]):
                candidate = None
                if c > 0 and grid[r][c - 1] != room["name"] and ("v", c, r) not in used:
                    x, y0, y1 = ix0 + c * cell_w, iy0 + r * cell_h, iy0 + (r + 1) * cell_h
                    w = min(INTERIOR_DOOR_WIDTH, (y1 - y0) * 0.8)
                    candidate = ((x, y0 + ((y1 - y0) - w) / 2.0, 0.0), w, 90.0, ("v", c, r))
                elif c < GRID_COLS - 1 and grid[r][c + 1] != room["name"] and ("v", c + 1, r) not in used:
                    x, y0, y1 = ix0 + (c + 1) * cell_w, iy0 + r * cell_h, iy0 + (r + 1) * cell_h
                    w = min(INTERIOR_DOOR_WIDTH, (y1 - y0) * 0.8)
                    candidate = ((x, y0 + ((y1 - y0) - w) / 2.0, 0.0), w, 90.0, ("v", c + 1, r))
                elif r > 0 and grid[r - 1][c] != room["name"] and ("h", r, c) not in used:
                    y, x0, x1 = iy0 + r * cell_h, ix0 + c * cell_w, ix0 + (c + 1) * cell_w
                    w = min(INTERIOR_DOOR_WIDTH, (x1 - x0) * 0.8)
                    candidate = ((x0 + ((x1 - x0) - w) / 2.0, y, 0.0), w, 0.0, ("h", r, c))
                elif r < GRID_ROWS - 1 and grid[r + 1][c] != room["name"] and ("h", r + 1, c) not in used:
                    y, x0, x1 = iy0 + (r + 1) * cell_h, ix0 + c * cell_w, ix0 + (c + 1) * cell_w
                    w = min(INTERIOR_DOOR_WIDTH, (x1 - x0) * 0.8)
                    candidate = ((x0 + ((x1 - x0) - w) / 2.0, y, 0.0), w, 0.0, ("h", r + 1, c))
                if candidate is None:
                    continue
                hinge, w, angle, key = candidate
                tag = f"door:{len(doors)}"
                doors.append({"room": room["name"], "kind": "interior", "tag": tag,
                              **door_symbol(plan, hinge, w, angle, tag)})
                used.add(key)
                placed = True
                break
        placed_doors.add(room["name"])

    windows = []
    for room in rooms:
        x0, y0, x1, y1 = room_rects[room["name"]]
        candidates = []
        if abs(x0 - ix0) < 1e-6 and room["name"] != entry_room:
            candidates.append(((0.0, (y0 + y1) / 2.0, 0.0), 90.0, y1 - y0))
        if abs(x1 - ix1) < 1e-6:
            candidates.append(((width_in, (y0 + y1) / 2.0, 0.0), 90.0, y1 - y0))
        if abs(y1 - iy1) < 1e-6:
            candidates.append((((x0 + x1) / 2.0, length_in, 0.0), 0.0, x1 - x0))
        if abs(y0 - iy0) < 1e-6 and room["name"] != entry_room:
            candidates.append((((x0 + x1) / 2.0, 0.0, 0.0), 0.0, x1 - x0))
        if not candidates:
            continue
        mid, angle, span = candidates[0]
        length = min(WINDOW_LENGTH, span * 0.8)
        d = (math.cos(math.radians(angle)), math.sin(math.radians(angle)))
        start = (mid[0] - d[0] * length / 2.0, mid[1] - d[1] * length / 2.0, mid[2])
        tag = f"window:{len(windows)}"
        windows.append({"room": room["name"], "tag": tag,
                        **window_symbol(plan, start, length, EXTERIOR_WALL_THICKNESS, angle, tag)})

    plan.meta = {"width_in": width_in, "length_in": length_in, "rooms": room_rows, "doors": doors,
                 "windows": windows, "exterior_wall_count": 4, "interior_wall_count": interior}
    return plan


# ======= V0.2.3 result shape (shared by both backends) =======

INCH = 1  # INSUNITS code

VALID_UNITS = {"INCHES", "FEET"}


def grid_plan_result(plan, handles, *, width_ft, length_ft, units_label, drawing_code, identity, dry_run) -> dict:
    """The V0.2.3 result shape, in the drawing's units (identical to V0.2.3
    in an inch drawing)."""
    factor = units.convert(1.0, INCH, drawing_code)
    meta = plan.meta

    def s(value):
        if isinstance(value, (tuple, list)):
            return type(value)(round(v * factor, 6) if isinstance(v, float) else v for v in value)
        return value * factor

    def h(tag):
        return handles.get(tag) if handles else None

    rooms = [{"name": r["name"], "bounds": [round(v * factor, 3) for v in r["bounds"]],
              "label_handle": h(r["label_tag"])} for r in meta["rooms"]]
    if units_label == "FEET":
        to_ft = units.convert(1.0, drawing_code, units.unit_code("ft"))
        for room in rooms:
            room["bounds_ft"] = [round(v * to_ft, 3) for v in room["bounds"]]
    doors = []
    for d in meta["doors"]:
        t = d["tag"]
        doors.append({
            "room": d["room"], "kind": d["kind"], "status": "ok",
            "hinge_point": s(d["hinge_point"]), "latch_point": s(d["latch_point"]), "leaf_end": s(d["leaf_end"]),
            "width": s(d["width"]), "angle_deg": d["angle_deg"],
            "hinge_jamb_handle": h(f"{t}:hinge_jamb"), "latch_jamb_handle": h(f"{t}:latch_jamb"),
            "leaf_handle": h(f"{t}:leaf"), "arc_handle": h(f"{t}:arc"),
        })
    windows = []
    for w in meta["windows"]:
        t = w["tag"]
        windows.append({
            "room": w["room"], "status": "ok",
            "start_point": s(w["start_point"]), "end_point": s(w["end_point"]), "length": s(w["length"]),
            "wall_thickness": s(w["wall_thickness"]), "angle_deg": w["angle_deg"],
            "line_handles": [h(f"{t}:line{i}") for i in range(3)],
        })
    exterior = [h(f"ext_wall:{i}") for i in range(meta["exterior_wall_count"])]
    interior = [h(f"int_wall:{i}") for i in range(meta["interior_wall_count"])]
    result = {
        "status": "ok",
        "width_ft": width_ft,
        "length_ft": length_ft,
        "units": units_label,
        "drawing_unit": units.describe(drawing_code),
        "exterior_walls": exterior,
        "interior_walls": interior,
        "rooms": rooms,
        "doors": doors,
        "windows": windows,
        "drawing_identity": identity,
        "dry_run": dry_run,
        "message": (
            f"{'Planned' if dry_run else 'Generated'} {width_ft:g}x{length_ft:g} ft floor plan with {len(rooms)} rooms, "
            f"{len(exterior)} exterior wall segments, {len(interior)} interior partitions, "
            f"{len(doors)} doors, {len(windows)} windows."
        ),
    }
    if dry_run:
        result["plan"] = plan.summary()
    else:
        result.update(verified=True, verification="modelspace_count_grew_by_planned_entity_count",
                      entity_count=len(plan.primitives))
    return result


def build_grid_plan(width_ft, length_ft, rooms_config):
    base = plan_grid_floor_plan(width_ft, length_ft, rooms_config)  # validates before any COM

    def build(code):
        return scale_plan(base, units.convert(1.0, INCH, code))

    return base, build


# ======= explicit-room planner =======

SIDES = ("south", "east", "north", "west")


def _num(value, label):
    return geometry.validate_number(value, label)


def validate_rooms(rooms) -> list[dict]:
    if not isinstance(rooms, list) or not rooms:
        raise geometry.ValidationError("rooms must be a non-empty list of {name, x, y, width, depth}")
    if len(rooms) > 60:
        raise geometry.ValidationError("at most 60 rooms per plan")
    out, names = [], set()
    for i, room in enumerate(rooms):
        if not isinstance(room, dict):
            raise geometry.ValidationError(f"rooms[{i}] must be an object")
        name = room.get("name")
        if not isinstance(name, str) or not name.strip():
            raise geometry.ValidationError(f"rooms[{i}].name must be a non-empty string")
        if name.lower() in names:
            raise geometry.ValidationError(f"room name {name!r} is used twice")
        names.add(name.lower())
        x, y = _num(room.get("x", 0.0), f"rooms[{i}].x"), _num(room.get("y", 0.0), f"rooms[{i}].y")
        w = geometry.validate_positive(room.get("width"), f"rooms[{i}].width")
        d = geometry.validate_positive(room.get("depth"), f"rooms[{i}].depth")
        out.append({"name": name.strip(), "x0": x, "y0": y, "x1": x + w, "y1": y + d})
    for i, a in enumerate(out):
        for b in out[i + 1:]:
            if min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]) > 1e-9 and min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]) > 1e-9:
                raise geometry.ValidationError(f"rooms {a['name']!r} and {b['name']!r} overlap")
    return out


def _edge_segments(rooms):
    """Split every room edge at every breakpoint on its line and classify each
    piece: exterior (one room) or interior (two rooms)."""
    from collections import defaultdict

    lines = defaultdict(list)  # ("v", x) or ("h", y) -> [(a, b, room_index, side)]
    for idx, r in enumerate(rooms):
        lines[("h", r["y0"])].append((r["x0"], r["x1"], idx, "south"))
        lines[("h", r["y1"])].append((r["x0"], r["x1"], idx, "north"))
        lines[("v", r["x0"])].append((r["y0"], r["y1"], idx, "west"))
        lines[("v", r["x1"])].append((r["y0"], r["y1"], idx, "east"))
    segments = []
    for (orient, pos), spans in lines.items():
        cuts = sorted({v for a, b, _, _ in spans for v in (a, b)})
        for a, b in zip(cuts, cuts[1:]):
            if b - a <= 1e-9:
                continue
            owners = [(idx, side) for s0, s1, idx, side in spans if s0 <= a + 1e-9 and s1 >= b - 1e-9]
            if owners:
                segments.append({"orient": orient, "pos": pos, "a": a, "b": b, "owners": owners})
    return segments


def _merge(segments):
    """Merge collinear touching segments with the same owners into walls."""
    walls = []
    key = lambda s: (s["orient"], s["pos"], tuple(sorted(o[0] for o in s["owners"])))
    for seg in sorted(segments, key=lambda s: (key(s), s["a"])):
        if walls and key(walls[-1]) == key(seg) and abs(walls[-1]["b"] - seg["a"]) < 1e-9:
            walls[-1]["b"] = seg["b"]
        else:
            walls.append(dict(seg))
    return walls


def _wall_points(wall):
    if wall["orient"] == "h":
        return (wall["a"], wall["pos"], 0.0), (wall["b"], wall["pos"], 0.0)
    return (wall["pos"], wall["a"], 0.0), (wall["pos"], wall["b"], 0.0)


def plan_room_floor_plan(rooms, unit_code: int, drawing_code: int, *, exterior_wall=None, interior_wall=None,
                         doors=None, windows="auto", entry_room=None, door_width=None, main_door_width=None,
                         window_width=None, label_height=None, dimensions=True, origin=(0.0, 0.0)) -> Plan:
    """rooms are rectangles in `unit_code` units, measured to wall centrelines;
    everything is converted into `drawing_code` units. Returns a Plan whose
    meta holds room / door / window schedules."""
    rooms = validate_rooms(rooms)
    factor = units.convert(1.0, unit_code, drawing_code)
    defaults = units.defaults_for(drawing_code)
    ox, oy = (_num(origin[0], "origin.x"), _num(origin[1], "origin.y")) if origin else (0.0, 0.0)

    def size(value, default, label):
        return defaults[default] if value is None else geometry.validate_positive(value, label) * factor

    t_ext = size(exterior_wall, "exterior_wall", "exterior_wall")
    t_int = size(interior_wall, "interior_wall", "interior_wall")
    w_door = size(door_width, "interior_door", "door_width")
    w_main = size(main_door_width, "main_door", "main_door_width")
    w_window = size(window_width, "window", "window_width")
    h_label = size(label_height, "text_height", "label_height")

    for r in rooms:  # into drawing units, shifted to origin
        for k in ("x0", "x1"):
            r[k] = r[k] * factor + ox
        for k in ("y0", "y1"):
            r[k] = r[k] * factor + oy

    walls = _merge(_edge_segments(rooms))
    plan = Plan()
    for name, color in (("A-WALL-EXT", 3), ("A-WALL-INT", 2), ("A-DOOR", 1), ("A-GLAZ", 4), ("A-TEXT", 7),
                        ("A-DIM", 6)):
        plan.layer(name, color)

    ext_walls, int_walls = [], []
    for i, wall in enumerate(walls):
        p1, p2 = _wall_points(wall)
        exterior = len(wall["owners"]) == 1
        thickness = t_ext if exterior else t_int
        layer = "A-WALL-EXT" if exterior else "A-WALL-INT"
        tag = f"{'ext' if exterior else 'int'}_wall:{len(ext_walls) if exterior else len(int_walls)}"
        plan.add(Primitive("polyline", layer, tag, closed=True,
                           points=tuple(geometry.wall_outline_points(p1, p2, thickness))))
        (ext_walls if exterior else int_walls).append({**wall, "tag": tag, "thickness": thickness})

    by_name = {r["name"].lower(): i for i, r in enumerate(rooms)}

    def room_index(name, label):
        if not isinstance(name, str) or name.lower() not in by_name:
            raise geometry.ValidationError(f"{label} names unknown room {name!r}")
        return by_name[name.lower()]

    shared = {}
    for wall in int_walls:
        a, b = sorted(o[0] for o in wall["owners"])
        if (a, b) not in shared or (wall["b"] - wall["a"]) > (shared[(a, b)]["b"] - shared[(a, b)]["a"]):
            shared[(a, b)] = wall

    entry = 0 if entry_room is None else room_index(entry_room, "entry_room")
    door_rows = []

    def place_door(wall, width, kind, rooms_pair, fraction=0.5):
        length = wall["b"] - wall["a"]
        clearance = 0.1 * length
        if width > length - 2 * min(clearance, wall.get("thickness", t_int)):
            raise geometry.ValidationError(
                f"door width {width:g} does not fit the {length:g}-long wall between {rooms_pair}")
        start = wall["a"] + (length - width) * min(max(fraction, 0.0), 1.0)
        if wall["orient"] == "h":
            hinge, angle = (start, wall["pos"], 0.0), 0.0
        else:
            hinge, angle = (wall["pos"], start, 0.0), 90.0
        tag = f"door:{len(door_rows)}"
        info = door_symbol(plan, hinge, width, angle, tag,
                           leaf_thickness=units.convert(DOOR_LEAF_THICKNESS_IN, 1, drawing_code),
                           frame_depth=units.convert(DOOR_FRAME_DEPTH_IN, 1, drawing_code))
        door_rows.append({"mark": f"D{len(door_rows) + 1}", "tag": tag, "kind": kind, "between": rooms_pair,
                          "width": width, **info})

    # main entry door: longest south (else any) exterior wall of the entry room
    entry_walls = [w for w in ext_walls if w["owners"][0][0] == entry]
    if entry_walls:
        south = [w for w in entry_walls if w["owners"][0][1] == "south"]
        wall = max(south or entry_walls, key=lambda w: w["b"] - w["a"])
        place_door(wall, w_main, "main", [rooms[entry]["name"], "exterior"])
    main_wall_tag = door_rows[0]["tag"] if door_rows else None

    if doors is None:
        # spanning tree from the entry room over rooms that share a wall long enough
        adjacency = {}
        for (a, b), wall in shared.items():
            if wall["b"] - wall["a"] >= w_door * 1.25:
                adjacency.setdefault(a, []).append(b)
                adjacency.setdefault(b, []).append(a)
        seen, queue = {entry}, deque([entry])
        while queue:
            current = queue.popleft()
            for nxt in sorted(adjacency.get(current, [])):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
                    place_door(shared[tuple(sorted((current, nxt)))], w_door, "interior",
                               [rooms[current]["name"], rooms[nxt]["name"]])
        unreachable = [rooms[i]["name"] for i in range(len(rooms)) if i not in seen]
    else:
        if not isinstance(doors, list):
            raise geometry.ValidationError("doors must be a list of {between: [room, room], width?, position?}")
        unreachable = []
        for i, door in enumerate(doors):
            pair = door.get("between") if isinstance(door, dict) else None
            if not isinstance(pair, list) or len(pair) != 2:
                raise geometry.ValidationError(f"doors[{i}].between must name two rooms")
            a, b = sorted((room_index(pair[0], f"doors[{i}]"), room_index(pair[1], f"doors[{i}]")))
            if (a, b) not in shared:
                raise geometry.ValidationError(f"rooms {pair[0]!r} and {pair[1]!r} share no wall")
            width = size(door.get("width"), "interior_door", f"doors[{i}].width")
            position = door.get("position", 0.5)
            place_door(shared[(a, b)], width, "interior", [rooms[a]["name"], rooms[b]["name"]],
                       fraction=geometry.validate_number(position, f"doors[{i}].position"))

    window_rows = []
    if windows == "auto":
        for idx, room in enumerate(rooms):
            own = [w for w in ext_walls if w["owners"][0][0] == idx]
            if idx == entry and main_wall_tag:
                own = [w for w in own if w["owners"][0][1] != "south"] or own
            if not own:
                continue
            wall = max(own, key=lambda w: w["b"] - w["a"])
            length = wall["b"] - wall["a"]
            width = min(w_window, length * 0.6)
            mid = (wall["a"] + wall["b"]) / 2.0
            if idx == entry and main_wall_tag and wall["owners"][0][1] == "south":
                # The entry door is centred on this wall: use the free stretch left of it.
                door_start = wall["a"] + (length - w_main) / 2.0
                margin = 0.1 * length
                free = door_start - wall["a"] - 2 * margin
                if free < min(width, w_window * 0.5):
                    continue  # no room for a window beside the door
                width = min(width, free)
                mid = wall["a"] + margin + width / 2.0
            start = (mid - width / 2.0, wall["pos"], 0.0) if wall["orient"] == "h" else (wall["pos"], mid - width / 2.0, 0.0)
            angle = 0.0 if wall["orient"] == "h" else 90.0
            tag = f"window:{len(window_rows)}"
            info = window_symbol(plan, start, width, t_ext, angle, tag)
            window_rows.append({"mark": f"W{len(window_rows) + 1}", "tag": tag, "room": room["name"],
                                "side": wall["owners"][0][1], **info})
    elif windows not in (None, "none", []):
        raise geometry.ValidationError('windows must be "auto" or "none"')

    room_rows = []
    to_m = units.convert(1.0, drawing_code, units.unit_code("m"))
    for idx, r in enumerate(rooms):
        cl_w, cl_d = r["x1"] - r["x0"], r["y1"] - r["y0"]

        def half(side_walls):
            return max((w["thickness"] for w in side_walls), default=0.0) / 2.0

        def walls_on(side):
            return [w for w in ext_walls + int_walls if any(o == (idx, side) for o in w["owners"])]

        net_w = cl_w - half(walls_on("west")) - half(walls_on("east"))
        net_d = cl_d - half(walls_on("south")) - half(walls_on("north"))
        area_m2 = max(net_w, 0) * max(net_d, 0) * to_m * to_m
        area_text = f"{area_m2:.2f} m²" if units.is_metric(drawing_code) else f"{area_m2 * 10.7639:.0f} ft²"
        center = ((r["x0"] + r["x1"]) / 2.0, (r["y0"] + r["y1"]) / 2.0, 0.0)
        tag = f"room_label:{idx}"
        plan.add(Primitive("mtext", "A-TEXT", tag, text=f"{r['name']}\\P{area_text}", location=center,
                           width=max(net_w * 0.8, h_label * 4), height=h_label, attach="middle_center"))
        room_rows.append({"name": r["name"], "centreline_bounds": [r["x0"], r["y0"], r["x1"], r["y1"]],
                          "clear_width": net_w, "clear_depth": net_d, "clear_area_m2": round(area_m2, 3),
                          "label": area_text, "label_tag": tag})

    if dimensions:
        xs = [v for r in rooms for v in (r["x0"], r["x1"])]
        ys = [v for r in rooms for v in (r["y0"], r["y1"])]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        gap = t_ext * 4
        plan.add(Primitive("dim_linear", "A-DIM", "dim:overall_x", points=((x0, y0, 0.0), (x1, y0, 0.0)),
                           location=(x0, y0 - gap, 0.0), rotation=0.0, height=h_label))
        plan.add(Primitive("dim_linear", "A-DIM", "dim:overall_y", points=((x0, y0, 0.0), (x0, y1, 0.0)),
                           location=(x0 - gap, y0, 0.0), rotation=90.0, height=h_label))

    plan.meta = {
        "rooms": room_rows,
        "doors": door_rows,
        "windows": window_rows,
        "walls": {"exterior": len(ext_walls), "interior": len(int_walls), "exterior_thickness": t_ext,
                  "interior_thickness": t_int},
        "unreachable_rooms": unreachable,
        "drawing_unit": units.describe(drawing_code),
        "input_unit": units.describe(unit_code),
    }
    return plan


# ======= grids.py =======
import string


LAYERS = {"S-GRID": (8, "CENTER"), "S-GRID-IDEN": (2, None), "S-COLS": (4, None), "S-ANNO-DIMS": (6, None)}


def _spacings(values, label):
    if not isinstance(values, list) or not values:
        raise geometry.ValidationError(f"{label} must be a non-empty list of bay widths")
    if len(values) > 100:
        raise geometry.ValidationError(f"{label} has more than 100 bays")
    return [geometry.validate_positive(v, f"{label}[{i}]") for i, v in enumerate(values)]


def letters(count: int, skip=("I", "O")) -> list[str]:
    alphabet = [c for c in string.ascii_uppercase if c not in set(skip or ())]
    out = []
    n = 0
    while len(out) < count:
        label, k = "", n
        while True:
            label = alphabet[k % len(alphabet)] + label
            k = k // len(alphabet) - 1
            if k < 0:
                break
        out.append(label)
        n += 1
    return out


def plan_grid(x_spacings, y_spacings, unit_code: int, drawing_code: int, *, origin=(0.0, 0.0),
              extension=None, bubble_diameter=None, text_height=None, column_size=None,
              skip_letters=True, dimensions=True) -> Plan:
    xs_in = _spacings(x_spacings, "x_spacings")
    ys_in = _spacings(y_spacings, "y_spacings")
    f = units.convert(1.0, unit_code, drawing_code)
    ox = geometry.validate_number(origin[0], "origin.x")
    oy = geometry.validate_number(origin[1], "origin.y")
    # paper-based defaults: 10 mm bubbles / 3.5 mm text at 1:100, as drawing units
    mm = units.convert(1.0, units.unit_code("mm"), drawing_code)
    ext = (geometry.validate_positive(extension, "extension") * f) if extension is not None else 1500 * mm
    bubble = (geometry.validate_positive(bubble_diameter, "bubble_diameter") * f) if bubble_diameter is not None else 1000 * mm
    th = (geometry.validate_positive(text_height, "text_height") * f) if text_height is not None else 350 * mm
    col = None
    if column_size is not None:
        if not isinstance(column_size, list) or len(column_size) != 2:
            raise geometry.ValidationError("column_size must be [width, depth]")
        col = (geometry.validate_positive(column_size[0], "column_size[0]") * f,
               geometry.validate_positive(column_size[1], "column_size[1]") * f)

    xs = [ox]
    for s in xs_in:
        xs.append(xs[-1] + s * f)
    ys = [oy]
    for s in ys_in:
        ys.append(ys[-1] + s * f)
    x0, x1, y0, y1 = xs[0], xs[-1], ys[0], ys[-1]
    r = bubble / 2.0

    plan = Plan()
    for name, (color, linetype) in LAYERS.items():
        plan.layer(name, color, linetype)

    numbers = [str(i + 1) for i in range(len(xs))]
    row_labels = letters(len(ys), skip=("I", "O") if skip_letters else ())
    for i, x in enumerate(xs):
        top = y1 + ext
        plan.add(Primitive("line", "S-GRID", f"grid:x:{numbers[i]}", points=((x, y0 - ext, 0.0), (x, top, 0.0))))
        center = (x, top + r, 0.0)
        plan.add(Primitive("circle", "S-GRID-IDEN", f"bubble:x:{numbers[i]}", center=center, radius=r))
        plan.add(Primitive("mtext", "S-GRID-IDEN", f"label:x:{numbers[i]}", text=numbers[i], location=center,
                           height=th, width=0.0, attach="middle_center"))
    for j, y in enumerate(ys):
        left = x0 - ext
        plan.add(Primitive("line", "S-GRID", f"grid:y:{row_labels[j]}", points=((left, y, 0.0), (x1 + ext, y, 0.0))))
        center = (left - r, y, 0.0)
        plan.add(Primitive("circle", "S-GRID-IDEN", f"bubble:y:{row_labels[j]}", center=center, radius=r))
        plan.add(Primitive("mtext", "S-GRID-IDEN", f"label:y:{row_labels[j]}", text=row_labels[j], location=center,
                           height=th, width=0.0, attach="middle_center"))

    columns = []
    if col is not None:
        for i, x in enumerate(xs):
            for j, y in enumerate(ys):
                mark = f"{row_labels[j]}{numbers[i]}"
                pts = rect_points(x - col[0] / 2, y - col[1] / 2, x + col[0] / 2, y + col[1] / 2)
                plan.add(Primitive("polyline", "S-COLS", f"column:{mark}", points=pts, closed=True,
                                   polyline_kind="2d"))
                plan.add(Primitive("hatch", "S-COLS", f"column_fill:{mark}", points=pts, pattern="SOLID"))
                columns.append({"mark": mark, "center": [x, y], "size": list(col)})

    if dimensions:
        gap1, gap2 = ext * 0.5, ext * 0.8
        for i in range(len(xs) - 1):
            plan.add(Primitive("dim_linear", "S-ANNO-DIMS", f"dim:x:{i}", points=((xs[i], y0, 0.0), (xs[i + 1], y0, 0.0)),
                               location=(xs[i], y0 - gap1, 0.0), rotation=0.0, height=th))
        if len(xs) > 2:
            plan.add(Primitive("dim_linear", "S-ANNO-DIMS", "dim:x:overall", points=((x0, y0, 0.0), (x1, y0, 0.0)),
                               location=(x0, y0 - gap2, 0.0), rotation=0.0, height=th))
        for j in range(len(ys) - 1):
            plan.add(Primitive("dim_linear", "S-ANNO-DIMS", f"dim:y:{j}", points=((x1, ys[j], 0.0), (x1, ys[j + 1], 0.0)),
                               location=(x1 + gap1, ys[j], 0.0), rotation=90.0, height=th))
        if len(ys) > 2:
            plan.add(Primitive("dim_linear", "S-ANNO-DIMS", "dim:y:overall", points=((x1, y0, 0.0), (x1, y1, 0.0)),
                               location=(x1 + gap2, y0, 0.0), rotation=90.0, height=th))

    plan.meta = {
        "x_lines": [{"label": n, "x": x} for n, x in zip(numbers, xs)],
        "y_lines": [{"label": lab, "y": y} for lab, y in zip(row_labels, ys)],
        "columns": columns,
        "overall": {"x": x1 - x0, "y": y1 - y0},
        "drawing_unit": units.describe(drawing_code),
    }
    return plan


# ======= stairs.py =======


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


# ======= sheets.py =======

# (width, height) in millimetres, landscape.
PAPER_SIZES_MM = {
    "A0": (1189.0, 841.0), "A1": (841.0, 594.0), "A2": (594.0, 420.0), "A3": (420.0, 297.0), "A4": (297.0, 210.0),
    "ANSI_A": (279.4, 215.9), "ANSI_B": (431.8, 279.4), "ANSI_C": (558.8, 431.8), "ANSI_D": (863.6, 558.8),
    "ANSI_E": (1117.6, 863.6),
    "ARCH_A": (304.8, 228.6), "ARCH_B": (457.2, 304.8), "ARCH_C": (609.6, 457.2), "ARCH_D": (914.4, 609.6),
    "ARCH_E": (1219.2, 914.4),
}
TITLE_FIELDS = ("project", "title", "drawing_number", "scale", "date", "drawn_by", "checked_by", "sheet", "revision")


def plan_sheet(paper: str, scale: float, drawing_code: int, *, orientation="landscape", origin=(0.0, 0.0),
               fields: dict | None = None, binding_margin_mm=20.0, margin_mm=10.0) -> Plan:
    key = (paper or "").strip().upper().replace("-", "_").replace(" ", "_")
    if key not in PAPER_SIZES_MM:
        raise geometry.ValidationError(f"paper must be one of {sorted(PAPER_SIZES_MM)}, got {paper!r}")
    scale = geometry.validate_positive(scale, "scale")
    if orientation not in ("landscape", "portrait"):
        raise geometry.ValidationError("orientation must be 'landscape' or 'portrait'")
    fields = dict(fields or {})
    unknown = sorted(set(fields) - set(TITLE_FIELDS))
    if unknown:
        raise geometry.ValidationError(f"unknown title block fields {unknown}; allowed: {list(TITLE_FIELDS)}")
    for k, v in fields.items():
        if not isinstance(v, str):
            raise geometry.ValidationError(f"title block field {k!r} must be text")
    fields.setdefault("scale", f"1:{scale:g}")
    ox = geometry.validate_number(origin[0], "origin.x")
    oy = geometry.validate_number(origin[1], "origin.y")

    w_mm, h_mm = PAPER_SIZES_MM[key]
    if orientation == "portrait":
        w_mm, h_mm = h_mm, w_mm
    k = units.convert(1.0, units.unit_code("mm"), drawing_code) * scale  # paper mm -> drawing units

    def p(x_mm, y_mm):
        return (ox + x_mm * k, oy + y_mm * k, 0.0)

    plan = Plan()
    plan.layer("G-ANNO-TTLB", 7)
    plan.layer("G-ANNO-TTLB-TEXT", 7)
    plan.add(Primitive("polyline", "G-ANNO-TTLB", "sheet:edge", closed=True, polyline_kind="2d",
                       points=tuple(p(*q[:2]) for q in rect_points(0, 0, w_mm, h_mm))))
    left, right, bottom, top = binding_margin_mm, w_mm - margin_mm, margin_mm, h_mm - margin_mm
    plan.add(Primitive("polyline", "G-ANNO-TTLB", "sheet:frame", closed=True, polyline_kind="2d",
                       points=tuple(p(*q[:2]) for q in rect_points(left, bottom, right, top))))

    # Title block 180 x 63 mm, three columns of three fields, lower right inside the frame.
    tb_w, tb_h = min(180.0, right - left), 63.0
    tx0, ty0 = right - tb_w, bottom
    plan.add(Primitive("polyline", "G-ANNO-TTLB", "title:box", closed=True, polyline_kind="2d",
                       points=tuple(p(*q[:2]) for q in rect_points(tx0, ty0, right, ty0 + tb_h))))
    rows, cols = 3, 3
    cell_w, cell_h = tb_w / cols, tb_h / rows
    for r in range(1, rows):
        plan.add(Primitive("line", "G-ANNO-TTLB", f"title:row:{r}", points=(p(tx0, ty0 + r * cell_h), p(right, ty0 + r * cell_h))))
    for c in range(1, cols):
        plan.add(Primitive("line", "G-ANNO-TTLB", f"title:col:{c}", points=(p(tx0 + c * cell_w, ty0), p(tx0 + c * cell_w, ty0 + tb_h))))
    label_h, value_h = 2.5, 3.5
    order = ("project", "title", "drawing_number", "scale", "date", "sheet", "drawn_by", "checked_by", "revision")
    for index, name in enumerate(order):
        r, c = 2 - index // cols, index % cols
        x, y = tx0 + c * cell_w + 2.0, ty0 + (r + 1) * cell_h - 2.0
        plan.add(Primitive("mtext", "G-ANNO-TTLB-TEXT", f"title:label:{name}", text=name.replace("_", " ").upper(),
                           location=p(x, y), height=label_h * k, width=0.0))
        value = fields.get(name, "")
        if value:
            plan.add(Primitive("mtext", "G-ANNO-TTLB-TEXT", f"title:value:{name}", text=value,
                               location=p(x, y - label_h - 3.0), height=value_h * k, width=(cell_w - 4.0) * k))
    plan.meta = {
        "paper": key, "orientation": orientation, "paper_mm": [w_mm, h_mm], "scale": scale,
        "sheet_size_drawing_units": [w_mm * k, h_mm * k],
        "drawing_area": {"min": list(p(left, bottom)[:2]), "max": list(p(right, top)[:2]),
                         "title_block_min": list(p(tx0, ty0)[:2])},
        "fields": fields, "drawing_unit": units.describe(drawing_code),
    }
    return plan
