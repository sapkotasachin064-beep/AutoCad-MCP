"""Architectural tools over COM: draw_wall, the add_door_symbol /
add_window_symbol building blocks, the V0.2.3 generate_2d_floor_plan macro,
and (V0.3.0) plan-based generators -- floor plans from explicit rooms,
structural grids, stairs and sheets.

Since V0.3.0 the macros are planned in domain/ (pure, unit-aware) and drawn
by backends.targets.emit into the open document in one COM session, so a
floor plan with dozens of entities still does one get_connected_app /
get_active_document round trip; the same plans draw headlessly through the
DXF backend. Every macro accepts dry_run=True to return the plan without
drawing, and verifies that model space grew by exactly the planned count.
"""

from backends.targets import ComTarget, emit
from cad_engine import (
    com_initialized,
    get_active_document,
    get_connected_app,
    get_drawing_identity,
    read_insunits,
)
from domain import floorplan, units
from domain.architecture import Plan
from tools.layers import ensure_layer
from tools.primitives import draw_polyline
from utils import geometry

INCH = 1  # INSUNITS code


def _default_wall_thickness() -> float:
    """The standard exterior wall for the active drawing's INSUNITS (9 in /
    230 mm, see domain.units.DraftingDefaults). Applies the units preset
    first, as any drawing tool does, so the value matches what gets drawn."""
    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app)
        code = read_insunits(doc)
    if code is None:
        code = 1  # unreadable INSUNITS: V0.2.x behaviour (inches)
    return units.defaults_for(code)["exterior_wall"]


def draw_wall(start_point, end_point, thickness: float | None = None, layer: str = "A-WALL") -> dict:
    """Draw a wall as a closed double-line outline (a 4-point polyline)
    centered on the start_point-end_point centerline, offset by thickness/2
    on each side. Coordinates and thickness are in the drawing's units;
    thickness=None means the standard exterior wall for those units (9.0 in
    an inch drawing, the V0.2.x default; 230.0 in a millimetre drawing).
    Creates the layer (via ensure_layer) if it doesn't already exist."""
    start = geometry.validate_point_2d_or_3d(start_point, "start_point")
    end = geometry.validate_point_2d_or_3d(end_point, "end_point")
    if thickness is not None:
        thickness = geometry.validate_positive(thickness, "thickness")
    layer = geometry.validate_layer_name(layer)
    if thickness is None:
        geometry.wall_outline_points(start, end, 1.0)  # reject zero-length/3D walls before touching AutoCAD
        thickness = _default_wall_thickness()

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
        "verified": result.get("verified", False),
        "verification": result.get("verification"),
        "drawing_identity": result["drawing_identity"],
        "message": f"Created wall {result['handle']} from {start} to {end}, thickness {thickness}.",
    }


# ======= Door and window symbols (V0.2.3 internal building blocks) =======
#
# Same signatures and results as V0.2.3: doc is an already-open active
# document and the caller is inside com_initialized(). Geometry is in the
# drawing's own units, as before (the symbol constants -- 1.75 leaf, 4.5
# jamb tick -- are inches, as in V0.2.3).


def add_door_symbol(doc, insert_point, width: float = 36.0, angle_deg: float = 0.0) -> dict:
    hinge = geometry.validate_point_2d_or_3d(insert_point, "insert_point")
    width = geometry.validate_positive(width, "width")
    angle_deg = geometry.validate_angle_degrees(angle_deg, "angle_deg")
    plan = Plan()
    plan.layer("A-DOOR")
    info = floorplan.door_symbol(plan, hinge, width, angle_deg, "door")
    handles = emit(plan, ComTarget(doc))
    return {
        "status": "ok",
        **info,
        "hinge_jamb_handle": handles["door:hinge_jamb"],
        "latch_jamb_handle": handles["door:latch_jamb"],
        "leaf_handle": handles["door:leaf"],
        "arc_handle": handles["door:arc"],
    }


def add_window_symbol(doc, start_point, length: float = 48.0, wall_thickness: float = 9.0,
                      angle_deg: float = 0.0) -> dict:
    start = geometry.validate_point_2d_or_3d(start_point, "start_point")
    length = geometry.validate_positive(length, "length")
    wall_thickness = geometry.validate_positive(wall_thickness, "wall_thickness")
    angle_deg = geometry.validate_angle_degrees(angle_deg, "angle_deg")
    plan = Plan()
    plan.layer("A-GLAZ")
    info = floorplan.window_symbol(plan, start, length, wall_thickness, angle_deg, "window")
    handles = emit(plan, ComTarget(doc))
    return {"status": "ok", **info, "line_handles": [handles[f"window:line{i}"] for i in range(3)]}


# ======= Plan execution shared by every macro =======


def run_plan_com(build, *, dry_run: bool):
    """build(drawing_insunits) -> Plan. Opens the active drawing for writing
    (units policy applied), plans in its INSUNITS, then either returns the
    plan (dry run) or emits it. Returns (plan, handles|None, identity, code)."""
    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app, for_write=not dry_run)
        code = read_insunits(doc)
        if code is None:
            code = INCH  # unreadable INSUNITS: V0.2.x behaviour
        plan = build(code)
        identity = get_drawing_identity(doc).identity
        if dry_run:
            return plan, None, identity, code
        handles = emit(plan, ComTarget(doc))
        return plan, handles, identity, code


# ======= generate_2d_floor_plan (V0.2.3) =======

_VALID_UNITS = floorplan.VALID_UNITS
build_grid_plan = floorplan.build_grid_plan
grid_plan_result = floorplan.grid_plan_result


def generate_2d_floor_plan(
    width_ft: float = 24.0,
    length_ft: float = 30.0,
    units: str = "INCHES",
    rooms_config: list[dict] | None = None,
    dry_run: bool = False,
) -> dict:
    """V0.2.3 macro: 9" exterior walls (A-WALL-EXT) around a width_ft x
    length_ft footprint, 4.5" interior partitions (A-WALL-INT) on a fixed 2x3
    room grid (_DEFAULT_ROOMS_CONFIG; override with rooms_config), a 36" main
    entry door and a 30" door per room (A-DOOR), a 48" window per exterior
    room (A-GLAZ), and an MTEXT label per room (A-TEXT). Drawn in the
    drawing's own units (inches under the default Engineering preset, which
    reproduces V0.2.3 exactly). units ("INCHES"/"FEET") selects how room
    bounds are additionally reported (bounds_ft). dry_run=True returns the
    plan without drawing."""
    units_label = units
    if not isinstance(units_label, str) or units_label.upper() not in _VALID_UNITS:
        raise geometry.ValidationError(f"units must be one of {sorted(_VALID_UNITS)}, got {units_label!r}")
    units_label = units_label.upper()
    base, build = build_grid_plan(width_ft, length_ft, rooms_config)
    plan, handles, identity, code = run_plan_com(build, dry_run=dry_run)
    return grid_plan_result(plan, handles, width_ft=float(width_ft), length_ft=float(length_ft),
                            units_label=units_label, drawing_code=code, identity=identity, dry_run=dry_run)


# Kept for callers of the V0.2.3 module attributes.
_DEFAULT_ROOMS_CONFIG = floorplan.DEFAULT_ROOMS_CONFIG
GRID_COLS = floorplan.GRID_COLS
GRID_ROWS = floorplan.GRID_ROWS
EXTERIOR_WALL_THICKNESS = floorplan.EXTERIOR_WALL_THICKNESS
INTERIOR_WALL_THICKNESS = floorplan.INTERIOR_WALL_THICKNESS
