"""Architectural macro tools: draw_wall.

V0.2.2 ships draw_wall only. draw_building_outline/insert_door/insert_window
(layout generation, wall trimming, block placeholders) are deferred -- they
need real design decisions (multiline style, what block to insert for a
door/window) this milestone intentionally didn't make yet.
"""

from tools.layers import ensure_layer
from tools.primitives import draw_polyline
from utils import geometry


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
