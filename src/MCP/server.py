"""AutoCAD MCP server.

V0.1.0 foundation tools:
  autocad_get_status              - installed/running/connected/supported check
  autocad_launch_application      - launch AutoCAD and wait until ready
  autocad_create_test_drawing_with_line - new drawing, one line (0,0,0)-(100,100,0), saved

V0.2.0 drawing, editing, and analysis tools: see README.md for the full list.
"""

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.mcpserver import MCPServer

from autocad import config, connection, db, editing, entities, geometry, layers, opencode, scanning
from autocad.drawing import create_test_drawing_with_line

server = MCPServer(name="autocad-mcp")


@server.tool()
def autocad_get_status() -> dict:
    """Report whether AutoCAD 2021+ is installed, running, and reachable over COM,
    and whether this process appears to be running inside an OpenCode session."""
    status = dataclasses.asdict(connection.get_status())
    status["opencode"] = opencode.detect()
    return status


@server.tool()
def autocad_launch_application(timeout_seconds: float = 60) -> dict:
    """Launch AutoCAD if not already running, and wait until it answers COM calls.
    Does nothing destructive if AutoCAD is already running; just verifies it."""
    return dataclasses.asdict(connection.launch_and_wait(timeout=timeout_seconds))


@server.tool()
def autocad_create_test_drawing_with_line(output_dir: str | None = None) -> dict:
    """Create a new drawing, draw one line from (0,0,0) to (100,100,0), save it as
    mcp_test_<timestamp>.dwg under output_dir (default: Documents/AutoCAD MCP Output),
    and verify the entity and file exist. Requires AutoCAD to already be connected;
    call autocad_get_status / autocad_launch_application first."""
    return create_test_drawing_with_line(output_dir=output_dir)


# ======= V0.2.0: drawing creation and geometry =======


@server.tool()
def autocad_create_new_drawing(template: str | None = None) -> dict:
    """Create a new, unsaved AutoCAD drawing (Documents.Add). Never touches
    disk, so it cannot overwrite an existing file. template, if given, is a
    .dwt template path passed through to AutoCAD."""
    return entities.create_new_drawing(template=template)


@server.tool()
def autocad_draw_line(start_point: list[float], end_point: list[float], layer: str | None = None) -> dict:
    """Draw a line between two validated points in the active drawing's
    ModelSpace. Points are [x, y] or [x, y, z]; z defaults to 0."""
    return entities.draw_line(start_point, end_point, layer=layer)


@server.tool()
def autocad_draw_polyline(points: list[list[float]], closed: bool = False, layer: str | None = None) -> dict:
    """Draw a polyline through an ordered list of >=2 points ([x, y] or
    [x, y, z], z defaults to 0), optionally closed, as an AcDb3dPolyline."""
    return entities.draw_polyline(points, closed=closed, layer=layer)


@server.tool()
def autocad_draw_rectangle(
    corner1: list[float] | None = None,
    corner2: list[float] | None = None,
    base_point: list[float] | None = None,
    width: float | None = None,
    height: float | None = None,
    layer: str | None = None,
) -> dict:
    """Draw an axis-aligned rectangle (as a closed polyline). Give exactly
    one of: corner1 and corner2 (opposite corners, same z-plane), or
    base_point with positive width and height."""
    return entities.draw_rectangle(
        corner1=corner1, corner2=corner2, base_point=base_point, width=width, height=height, layer=layer
    )


@server.tool()
def autocad_draw_circle(center: list[float], radius: float, layer: str | None = None) -> dict:
    """Draw a circle at center ([x, y] or [x, y, z]) with a positive radius."""
    return entities.draw_circle(center, radius, layer=layer)


@server.tool()
def autocad_draw_text(
    text: str,
    insertion_point: list[float],
    height: float,
    rotation_degrees: float = 0.0,
    layer: str | None = None,
) -> dict:
    """Add single-line text at insertion_point with a positive height and an
    optional rotation in degrees (counterclockwise, viewed from +Z)."""
    return entities.draw_text(text, insertion_point, height, rotation_degrees=rotation_degrees, layer=layer)


# ======= V0.2.0: layers =======


@server.tool()
def autocad_create_layer(name: str, color_index: int | None = None, linetype: str | None = None) -> dict:
    """Create a layer if it doesn't exist. color_index (0-255) and linetype,
    when given, update that property on an existing layer; every other
    layer property (locked, frozen, on/off, ...) is left untouched."""
    return layers.create_layer(name, color_index=color_index, linetype=linetype)


# ======= V0.2.0: entity editing =======


@server.tool()
def autocad_move_entity(handle: str, displacement: list[float]) -> dict:
    """Move the entity with this handle by a validated [dx, dy, dz] vector."""
    return editing.move_entity(handle, displacement)


@server.tool()
def autocad_rotate_entity(handle: str, base_point: list[float], angle_degrees: float) -> dict:
    """Rotate the entity with this handle about base_point by angle_degrees
    (counterclockwise-positive, viewed from +Z -- AutoCAD's own convention)."""
    return editing.rotate_entity(handle, base_point, angle_degrees)


@server.tool()
def autocad_copy_entity(handle: str, displacement: list[float]) -> dict:
    """Copy the entity with this handle, offsetting the copy by a validated
    [dx, dy, dz] vector. Returns the new entity's handle."""
    return editing.copy_entity(handle, displacement)


@server.tool()
def autocad_highlight_entity(handle: str, method: str = "temporary", color: int = 1, clear: bool = False) -> dict:
    """Highlight an entity. method="temporary" uses AutoCAD's native
    Highlight() flag (a visual-only state, not saved to the DWG, that never
    touches the entity's Color property) -- pass clear=True to turn it back
    off. method="persistent" sets entity.Color (0-255) and does not revert."""
    return editing.highlight_entity(handle, method=method, color=color, clear=clear)


@server.tool()
def autocad_highlight_text_matches(
    pattern: str,
    use_regex: bool = False,
    method: str = "temporary",
    color: int = 1,
    clear: bool = False,
) -> dict:
    """Find TEXT/MTEXT entities matching pattern (literal substring, or a
    regex if use_regex=True) and highlight them the same way as
    autocad_highlight_entity. Never modifies the matched entities' text."""
    return editing.highlight_text_matches(pattern, use_regex=use_regex, method=method, color=color, clear=clear)


# ======= V0.2.0: drawing analysis and database =======


@server.tool()
def autocad_scan_all_entities() -> dict:
    """Scan top-level ModelSpace entities (lines, circles, polylines,
    text/mtext -- not block references or PaperSpace) and replace this
    drawing's snapshot in the local SQLite database (other drawings'
    records are untouched; rescanning is idempotent)."""
    return scanning.scan_all_entities()


@server.tool()
def autocad_count_text_patterns(pattern: str, use_regex: bool = False) -> dict:
    """Count TEXT/MTEXT entities in the active drawing whose text matches
    pattern: a literal substring by default, or a regex if use_regex=True."""
    return scanning.count_text_patterns(pattern, use_regex=use_regex)


@server.tool()
def autocad_execute_query(query: str, params: list | None = None) -> dict:
    """Run one read-only SELECT (optionally with a WITH clause) against the
    scanned-entities database. Writes, DDL, PRAGMA, and multi-statement
    input are rejected; use params for a parameterized query (never string-
    format user values into the query text)."""
    result = db.execute_readonly_query(config.get_db_path(), query, params=params)
    return {
        "status": "ok",
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
    }


if __name__ == "__main__":
    server.run("stdio")
