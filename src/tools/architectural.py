"""Architectural macro tools: draw_wall, add_door_symbol, add_window_symbol,
and the generate_2d_floor_plan macro that composes them into a full
residential floor plan in one COM session.

generate_2d_floor_plan and the add_*_symbol helpers draw directly via
win32com (AddLine/Add3DPoly/AddArc/AddMText on a doc/ModelSpace obtained
once) instead of going through tools/primitives.py's per-call tool wrappers,
so a floor plan with dozens of entities does one get_connected_app/
get_active_document round trip, not one per line. add_door_symbol and
add_window_symbol take `doc` directly and are internal building blocks, not
validated standalone MCP tools in their own right -- callers must already be
inside a com_initialized() context with doc the active document.
"""

import math

from cad_engine import (
    _retry_com,
    com_initialized,
    flat_variant,
    get_active_document,
    get_connected_app,
    get_drawing_identity,
    point_variant,
)
from tools.layers import apply_layer_to_entity, ensure_layer, get_or_create_layer
from tools.primitives import draw_polyline
from utils import geometry
from utils.constants import ARCHITECTURAL_LAYERS


def draw_wall(start_point, end_point, thickness: float = 9.0, layer: str = "A-WALL") -> dict:
    """Draw a wall as a closed double-line outline (a 4-point polyline)
    centered on the start_point-end_point centerline, offset by thickness/2
    on each side. thickness is in the active drawing's current units, same
    as every other tool here -- this server never assumes inches/mm/feet
    and never converts between units (see README's Units and coordinates).
    Creates the layer (via ensure_layer) if it doesn't already exist."""
    start = geometry.validate_point_2d_or_3d(start_point, "start_point")
    end = geometry.validate_point_2d_or_3d(end_point, "end_point")
    thickness = geometry.validate_positive(thickness, "thickness")
    layer = geometry.validate_layer_name(layer)

    outline = geometry.wall_outline_points(start, end, thickness)
    ensure_layer(layer)
    result = draw_polyline(outline, closed=True, layer=layer)

    return {
        "status": "ok",
        "handle": result["handle"],
        "start_point": start,
        "end_point": end,
        "thickness": thickness,
        "layer": result["layer"],
        "outline": outline,
        "drawing_identity": result["drawing_identity"],
        "message": f"Created wall {result['handle']} from {start} to {end}, thickness {thickness}.",
    }


# ======= Low-level entity helpers (shared by the macro tools below) =======
#
# Unlike tools/primitives.py's draw_* functions, these take an already-open
# doc/model_space and skip the count-based verification primitives.py does
# per entity -- generate_2d_floor_plan calls these dozens of times in one
# COM session and verifies the overall result once, not entity-by-entity.


def _model_space(doc):
    return _retry_com(lambda: doc.ModelSpace)


def _add_line(doc, model_space, p1, p2, layer: str) -> str:
    line = _retry_com(lambda: model_space.AddLine(point_variant(p1), point_variant(p2)))
    apply_layer_to_entity(doc, line, layer)
    return line.Handle


def _add_closed_polyline(doc, model_space, points, layer: str) -> str:
    flat = [coord for point in points for coord in point]
    pline = _retry_com(lambda: model_space.Add3DPoly(flat_variant(flat)))
    _retry_com(lambda: setattr(pline, "Closed", True))
    apply_layer_to_entity(doc, pline, layer)
    return pline.Handle


def _add_arc(doc, model_space, center, radius: float, start_rad: float, end_rad: float, layer: str) -> str:
    arc = _retry_com(lambda: model_space.AddArc(point_variant(center), radius, start_rad, end_rad))
    apply_layer_to_entity(doc, arc, layer)
    return arc.Handle


def _add_mtext(doc, model_space, text: str, insertion_point, box_width: float, height: float, layer: str) -> str:
    mtext = _retry_com(lambda: model_space.AddMText(point_variant(insertion_point), box_width, text))
    _retry_com(lambda: setattr(mtext, "Height", height))
    apply_layer_to_entity(doc, mtext, layer)
    return mtext.Handle


# ======= Door and window symbols =======

_DOOR_LEAF_THICKNESS = 1.75  # standard solid-core door, inches
_DOOR_FRAME_DEPTH = 4.5  # jamb tick length -- a symbol constant, not tied to the actual wall thickness


def add_door_symbol(doc, insert_point, width: float = 36.0, angle_deg: float = 0.0) -> dict:
    """Draw one door symbol directly into doc's ModelSpace, on layer A-DOOR:
    a frame/jamb tick line at each edge of the opening, a thin door-leaf
    rectangle in the open (90-degree) position, and a quarter-circle swing
    arc from the hinge to the leaf.

    insert_point is the hinge (jamb) point. angle_deg is the direction of
    the wall the opening is cut into (0 = +X), counterclockwise-positive
    viewed from +Z -- the same rotation convention as autocad_rotate_entity/
    autocad_draw_text (see README's Units and coordinates). The leaf swings
    open towards angle_deg + 90.

    Internal building block, not a standalone MCP tool: caller must already
    be inside a com_initialized() context with doc the active document."""
    hinge = geometry.validate_point_2d_or_3d(insert_point, "insert_point")
    width = geometry.validate_positive(width, "width")
    angle_deg = geometry.validate_angle_degrees(angle_deg, "angle_deg")

    wall_rad = geometry.degrees_to_radians(angle_deg)
    swing_rad = geometry.degrees_to_radians(angle_deg + 90.0)
    wall_dir = (math.cos(wall_rad), math.sin(wall_rad))
    swing_dir = (math.cos(swing_rad), math.sin(swing_rad))
    z = hinge[2]

    latch_jamb = (hinge[0] + width * wall_dir[0], hinge[1] + width * wall_dir[1], z)
    leaf_end = (hinge[0] + width * swing_dir[0], hinge[1] + width * swing_dir[1], z)

    get_or_create_layer(doc, "A-DOOR")
    model_space = _model_space(doc)

    handles = {}
    half_frame = _DOOR_FRAME_DEPTH / 2.0
    for label, jamb in (("hinge_jamb_handle", hinge), ("latch_jamb_handle", latch_jamb)):
        p1 = (jamb[0] - half_frame * swing_dir[0], jamb[1] - half_frame * swing_dir[1], z)
        p2 = (jamb[0] + half_frame * swing_dir[0], jamb[1] + half_frame * swing_dir[1], z)
        handles[label] = _add_line(doc, model_space, p1, p2, "A-DOOR")

    leaf_outline = geometry.wall_outline_points(hinge, leaf_end, _DOOR_LEAF_THICKNESS)
    handles["leaf_handle"] = _add_closed_polyline(doc, model_space, leaf_outline, "A-DOOR")
    handles["arc_handle"] = _add_arc(doc, model_space, hinge, width, wall_rad, swing_rad, "A-DOOR")

    return {
        "status": "ok",
        "hinge_point": hinge,
        "latch_point": latch_jamb,
        "leaf_end": leaf_end,
        "width": width,
        "angle_deg": angle_deg,
        **handles,
    }


def add_window_symbol(
    doc,
    start_point,
    length: float = 48.0,
    wall_thickness: float = 9.0,
    angle_deg: float = 0.0,
) -> dict:
    """Draw one window symbol directly into doc's ModelSpace, on layer
    A-GLAZ: 3 parallel glazing lines spanning wall_thickness, each `length`
    long, running from start_point along angle_deg (0 = +X, same convention
    as add_door_symbol). angle_deg is not in the original task spec's
    signature but is needed to place a window on a wall that isn't aligned
    with +X (e.g. the left/right exterior wall of a floor plan) -- it
    defaults to 0.0 so every existing call without it behaves exactly as
    before.

    Internal building block, not a standalone MCP tool: same contract as
    add_door_symbol."""
    start = geometry.validate_point_2d_or_3d(start_point, "start_point")
    length = geometry.validate_positive(length, "length")
    wall_thickness = geometry.validate_positive(wall_thickness, "wall_thickness")
    angle_deg = geometry.validate_angle_degrees(angle_deg, "angle_deg")

    wall_rad = geometry.degrees_to_radians(angle_deg)
    wall_dir = (math.cos(wall_rad), math.sin(wall_rad))
    perp_dir = (-wall_dir[1], wall_dir[0])
    z = start[2]

    get_or_create_layer(doc, "A-GLAZ")
    model_space = _model_space(doc)

    line_handles = []
    for offset in (-wall_thickness / 2.0, 0.0, wall_thickness / 2.0):
        p1 = (start[0] + perp_dir[0] * offset, start[1] + perp_dir[1] * offset, z)
        p2 = (p1[0] + wall_dir[0] * length, p1[1] + wall_dir[1] * length, z)
        line_handles.append(_add_line(doc, model_space, p1, p2, "A-GLAZ"))

    end_point = (start[0] + wall_dir[0] * length, start[1] + wall_dir[1] * length, z)
    return {
        "status": "ok",
        "start_point": start,
        "end_point": end_point,
        "length": length,
        "wall_thickness": wall_thickness,
        "angle_deg": angle_deg,
        "line_handles": line_handles,
    }


# ======= generate_2d_floor_plan =======

EXTERIOR_WALL_THICKNESS = 9.0
INTERIOR_WALL_THICKNESS = 4.5
MAIN_DOOR_WIDTH = 36.0
INTERIOR_DOOR_WIDTH = 30.0
WINDOW_LENGTH = 48.0
ROOM_LABEL_HEIGHT = 6.0

# Fixed 2-column x 3-row grid: row 0 (bottom, where the main entry sits) is
# the living area, row 1 is the kitchen/bath split, row 2 is the bedrooms.
# rooms_config can override which named room occupies which cell(s), but not
# the grid dimensions themselves.
GRID_COLS = 2
GRID_ROWS = 3

_DEFAULT_ROOMS_CONFIG = [
    {"name": "Living Room", "col": 0, "row": 0, "col_span": 2, "row_span": 1},
    {"name": "Kitchen", "col": 0, "row": 1, "col_span": 1, "row_span": 1},
    {"name": "Bath", "col": 1, "row": 1, "col_span": 1, "row_span": 1},
    {"name": "Bedroom 1", "col": 0, "row": 2, "col_span": 1, "row_span": 1},
    {"name": "Bedroom 2", "col": 1, "row": 2, "col_span": 1, "row_span": 1},
]

_VALID_UNITS = {"INCHES", "FEET"}
_FLOOR_PLAN_LAYERS = ("A-WALL-EXT", "A-WALL-INT", "A-DOOR", "A-GLAZ", "A-TEXT", "A-DIM")

# Minimum footprint for the fixed 2x3 grid to produce rooms of any sane size.
_MIN_GRID_SPAN_INCHES = 180.0  # 15 ft


def _validate_rooms_config(rooms_config) -> list[dict]:
    if rooms_config is None:
        return [dict(room) for room in _DEFAULT_ROOMS_CONFIG]
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


def _build_room_grid(rooms: list[dict]) -> list[list[str | None]]:
    """Fill a GRID_ROWS x GRID_COLS occupancy grid with each room's name,
    raising if a room doesn't fit, overlaps another, or any cell is left
    uncovered -- generate_2d_floor_plan needs a fully-partitioned rectangle
    to place interior walls correctly."""
    grid: list[list[str | None]] = [[None] * GRID_COLS for _ in range(GRID_ROWS)]
    for room in rooms:
        if room["col"] + room["col_span"] > GRID_COLS or room["row"] + room["row_span"] > GRID_ROWS:
            raise geometry.ValidationError(
                f"room {room['name']!r} does not fit in the {GRID_COLS}x{GRID_ROWS} room grid"
            )
        for r in range(room["row"], room["row"] + room["row_span"]):
            for c in range(room["col"], room["col"] + room["col_span"]):
                if grid[r][c] is not None:
                    raise geometry.ValidationError(
                        f"room {room['name']!r} overlaps {grid[r][c]!r} at grid cell (col={c}, row={r})"
                    )
                grid[r][c] = room["name"]

    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            if grid[r][c] is None:
                raise geometry.ValidationError(
                    f"grid cell (col={c}, row={r}) is not covered by any room in rooms_config"
                )
    return grid


def generate_2d_floor_plan(
    width_ft: float = 24.0,
    length_ft: float = 30.0,
    units: str = "INCHES",
    rooms_config: list[dict] | None = None,
) -> dict:
    """Generate a complete residential floor plan in one COM session: 9"
    exterior walls (A-WALL-EXT) around a width_ft x length_ft footprint, 4.5"
    interior partition walls (A-WALL-INT) splitting it into a fixed 2x3 room
    grid (Living Room across the front, Kitchen/Bath, two Bedrooms -- see
    _DEFAULT_ROOMS_CONFIG), one 36"-wide main entry door and one 30"-wide
    interior door per room (add_door_symbol), one 48"-long window per room
    that touches an exterior wall (add_window_symbol), and an MTEXT room
    label (A-TEXT) at each room's center.

    width_ft/length_ft are the building footprint in feet; all drawing is
    done in inches (width_ft*12), matching the Engineering units this server
    now forces on every active document (cad_engine.set_engineering_units --
    LUNITS=3, INSUNITS=1). units selects how dimensions are reported back in
    this result (it does not change the drawing's actual unit system, which
    is always forced to Engineering/inches): "INCHES" (default) or "FEET".

    rooms_config, if given, replaces _DEFAULT_ROOMS_CONFIG: a list of
    {"name": str, "col": int, "row": int, "col_span": int, "row_span": int}
    (col_span/row_span default to 1) against the fixed GRID_COLS x GRID_ROWS
    grid. Every grid cell must end up covered by exactly one room.

    Requires AutoCAD to already be connected with a document open, same as
    every other tool here."""
    width_ft = geometry.validate_positive(width_ft, "width_ft")
    length_ft = geometry.validate_positive(length_ft, "length_ft")
    if not isinstance(units, str) or units.upper() not in _VALID_UNITS:
        raise geometry.ValidationError(f"units must be one of {sorted(_VALID_UNITS)}, got {units!r}")
    units = units.upper()
    rooms = _validate_rooms_config(rooms_config)
    grid = _build_room_grid(rooms)

    width_in = width_ft * 12.0
    length_in = length_ft * 12.0
    if width_in < _MIN_GRID_SPAN_INCHES or length_in < _MIN_GRID_SPAN_INCHES:
        raise geometry.ValidationError(
            f"width_ft/length_ft too small: footprint must be at least "
            f"{_MIN_GRID_SPAN_INCHES / 12.0:g} ft on each side for a {GRID_COLS}x{GRID_ROWS} room grid"
        )

    ix0, iy0 = EXTERIOR_WALL_THICKNESS / 2.0, EXTERIOR_WALL_THICKNESS / 2.0
    ix1, iy1 = width_in - EXTERIOR_WALL_THICKNESS / 2.0, length_in - EXTERIOR_WALL_THICKNESS / 2.0
    cell_w = (ix1 - ix0) / GRID_COLS
    cell_h = (iy1 - iy0) / GRID_ROWS

    def cell_rect(col, row, col_span, row_span):
        x0 = ix0 + col * cell_w
        x1 = ix0 + (col + col_span) * cell_w
        y0 = iy0 + row * cell_h
        y1 = iy0 + (row + row_span) * cell_h
        return x0, y0, x1, y1

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app)  # also forces Engineering units (cad_engine.set_engineering_units)
        model_space = _model_space(doc)

        for layer_name in _FLOOR_PLAN_LAYERS:
            layer = get_or_create_layer(doc, layer_name)
            color_index = ARCHITECTURAL_LAYERS[layer_name]["color_index"]
            _retry_com(lambda layer=layer, color_index=color_index: setattr(layer, "Color", color_index))

        # Exterior wall loop: 4 wall segments around the footprint's centerline rectangle.
        outline = [(0.0, 0.0, 0.0), (width_in, 0.0, 0.0), (width_in, length_in, 0.0), (0.0, length_in, 0.0)]
        exterior_wall_handles = []
        for i in range(4):
            seg_start, seg_end = outline[i], outline[(i + 1) % 4]
            wall_outline = geometry.wall_outline_points(seg_start, seg_end, EXTERIOR_WALL_THICKNESS)
            exterior_wall_handles.append(_add_closed_polyline(doc, model_space, wall_outline, "A-WALL-EXT"))

        # Interior partition walls: one segment per grid-line cell-edge where the two
        # rooms on either side differ (a room spanning multiple cells has no wall
        # drawn through its own interior).
        interior_wall_handles = []
        for c in range(1, GRID_COLS):
            x = ix0 + c * cell_w
            for r in range(GRID_ROWS):
                if grid[r][c - 1] != grid[r][c]:
                    y0 = iy0 + r * cell_h
                    y1 = iy0 + (r + 1) * cell_h
                    seg = geometry.wall_outline_points((x, y0, 0.0), (x, y1, 0.0), INTERIOR_WALL_THICKNESS)
                    interior_wall_handles.append(_add_closed_polyline(doc, model_space, seg, "A-WALL-INT"))
        for r in range(1, GRID_ROWS):
            y = iy0 + r * cell_h
            for c in range(GRID_COLS):
                if grid[r - 1][c] != grid[r][c]:
                    x0 = ix0 + c * cell_w
                    x1 = ix0 + (c + 1) * cell_w
                    seg = geometry.wall_outline_points((x0, y, 0.0), (x1, y, 0.0), INTERIOR_WALL_THICKNESS)
                    interior_wall_handles.append(_add_closed_polyline(doc, model_space, seg, "A-WALL-INT"))

        # Room rectangles + MTEXT labels.
        room_rects = {}
        room_results = []
        for room in rooms:
            x0, y0, x1, y1 = cell_rect(room["col"], room["row"], room["col_span"], room["row_span"])
            room_rects[room["name"]] = (x0, y0, x1, y1)
            center = ((x0 + x1) / 2.0, (y0 + y1) / 2.0, 0.0)
            box_width = max(x1 - x0 - 4.0, ROOM_LABEL_HEIGHT * 2.0)
            label_handle = _add_mtext(doc, model_space, room["name"], center, box_width, ROOM_LABEL_HEIGHT, "A-TEXT")
            room_results.append(
                {
                    "name": room["name"],
                    "bounds": [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)],
                    "label_handle": label_handle,
                }
            )

        # Main entry door: centered on the bottom exterior wall, into whichever room
        # occupies the front-center grid cell.
        entry_room = grid[0][GRID_COLS // 2]
        entry_hinge = (width_in / 2.0 - MAIN_DOOR_WIDTH / 2.0, 0.0, 0.0)
        door_results = [
            {"room": entry_room, "kind": "main", **add_door_symbol(doc, entry_hinge, width=MAIN_DOOR_WIDTH, angle_deg=0.0)}
        ]

        # One interior door per non-entry room, on the first unused partition-wall
        # boundary it touches (used_boundaries prevents two adjacent rooms from each
        # drawing their own overlapping door on the shared wall between them).
        placed_doors = {entry_room}
        used_boundaries: set[tuple[str, int, int]] = set()
        for room in rooms:
            if room["name"] in placed_doors:
                continue
            placed = False
            for r in range(room["row"], room["row"] + room["row_span"]):
                if placed:
                    break
                for c in range(room["col"], room["col"] + room["col_span"]):
                    if c > 0 and grid[r][c - 1] != room["name"] and ("v", c, r) not in used_boundaries:
                        x = ix0 + c * cell_w
                        y0, y1 = iy0 + r * cell_h, iy0 + (r + 1) * cell_h
                        door_width = min(INTERIOR_DOOR_WIDTH, (y1 - y0) * 0.8)
                        hinge = (x, y0 + ((y1 - y0) - door_width) / 2.0, 0.0)
                        door_results.append(
                            {"room": room["name"], "kind": "interior", **add_door_symbol(doc, hinge, width=door_width, angle_deg=90.0)}
                        )
                        used_boundaries.add(("v", c, r))
                        placed = True
                    elif c < GRID_COLS - 1 and grid[r][c + 1] != room["name"] and ("v", c + 1, r) not in used_boundaries:
                        x = ix0 + (c + 1) * cell_w
                        y0, y1 = iy0 + r * cell_h, iy0 + (r + 1) * cell_h
                        door_width = min(INTERIOR_DOOR_WIDTH, (y1 - y0) * 0.8)
                        hinge = (x, y0 + ((y1 - y0) - door_width) / 2.0, 0.0)
                        door_results.append(
                            {"room": room["name"], "kind": "interior", **add_door_symbol(doc, hinge, width=door_width, angle_deg=90.0)}
                        )
                        used_boundaries.add(("v", c + 1, r))
                        placed = True
                    elif r > 0 and grid[r - 1][c] != room["name"] and ("h", r, c) not in used_boundaries:
                        y = iy0 + r * cell_h
                        x0, x1 = ix0 + c * cell_w, ix0 + (c + 1) * cell_w
                        door_width = min(INTERIOR_DOOR_WIDTH, (x1 - x0) * 0.8)
                        hinge = (x0 + ((x1 - x0) - door_width) / 2.0, y, 0.0)
                        door_results.append(
                            {"room": room["name"], "kind": "interior", **add_door_symbol(doc, hinge, width=door_width, angle_deg=0.0)}
                        )
                        used_boundaries.add(("h", r, c))
                        placed = True
                    elif r < GRID_ROWS - 1 and grid[r + 1][c] != room["name"] and ("h", r + 1, c) not in used_boundaries:
                        y = iy0 + (r + 1) * cell_h
                        x0, x1 = ix0 + c * cell_w, ix0 + (c + 1) * cell_w
                        door_width = min(INTERIOR_DOOR_WIDTH, (x1 - x0) * 0.8)
                        hinge = (x0 + ((x1 - x0) - door_width) / 2.0, y, 0.0)
                        door_results.append(
                            {"room": room["name"], "kind": "interior", **add_door_symbol(doc, hinge, width=door_width, angle_deg=0.0)}
                        )
                        used_boundaries.add(("h", r + 1, c))
                        placed = True
                    else:
                        continue
                    break
            placed_doors.add(room["name"])

        # One window per room that touches an exterior wall (the entry room's
        # entry-side wall is skipped so the window doesn't collide with the door).
        window_results = []
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
            win_length = min(WINDOW_LENGTH, span * 0.8)
            wall_rad = geometry.degrees_to_radians(angle)
            wall_dir = (math.cos(wall_rad), math.sin(wall_rad))
            start = (mid[0] - wall_dir[0] * win_length / 2.0, mid[1] - wall_dir[1] * win_length / 2.0, mid[2])
            window_results.append(
                {
                    "room": room["name"],
                    **add_window_symbol(doc, start, length=win_length, wall_thickness=EXTERIOR_WALL_THICKNESS, angle_deg=angle),
                }
            )

        identity = get_drawing_identity(doc)

    return {
        "status": "ok",
        "width_ft": width_ft,
        "length_ft": length_ft,
        "units": units,
        "exterior_walls": exterior_wall_handles,
        "interior_walls": interior_wall_handles,
        "rooms": room_results,
        "doors": door_results,
        "windows": window_results,
        "drawing_identity": identity.identity,
        "message": (
            f"Generated {width_ft:g}x{length_ft:g} ft floor plan with {len(room_results)} rooms, "
            f"{len(exterior_wall_handles)} exterior wall segments, {len(interior_wall_handles)} interior "
            f"partitions, {len(door_results)} doors, {len(window_results)} windows."
        ),
    }
