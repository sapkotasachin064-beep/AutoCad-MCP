"""AutoCAD MCP server -- MCP registration only.

Every tool is declared with @cad_tool, which:
  * records a ToolSpec (toolset, side-effect kind, backend operation) in
    core.registry, the source of autocad_get_capabilities;
  * sets MCP ToolAnnotations (read-only / destructive / idempotent hints);
  * converts every exception into a ToolError whose text is a JSON envelope
    {"ok": false, "error": {"code", "message", "recoverable",
    "recommended_action", "details"}} -- MCP SDK 2.x would otherwise show
    the client only "Error executing tool <name>";
  * adds `backend` and, for tools that change something, a `state` block
    that keeps accepted / preflight / executed / verified / saved apart;
  * skips MCP registration when the tool's toolset is disabled by
    AUTOCAD_MCP_TOOLSETS (the function still exists for tests).

The work itself lives in backends/ (engine-specific), tools/ (live COM
implementations), domain/ (pure engineering logic) and schemas.py (typed
argument descriptions the MCP SDK turns into each tool's input schema).
"""

import functools
import inspect
import logging
import sys
from pathlib import Path
from typing import Annotated

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from backends import get_backend
from core import db, registry, session
from core.errors import CadError, error_text
from core.evidence import validate_limit
from core.executor import get_executor
from core.hosts import detect_opencode
from core.registry import ToolSpec
from domain import units
from schemas import Handle, Handles, Layer, LayerName, Point, Points
from utils.constants import get_db_path, get_output_dir
from version import __version__

log = logging.getLogger("autocad_mcp")

INSTRUCTIONS = """\
Drives AutoCAD 2021+ (full, not LT) over COM on Windows, or edits a DXF file headlessly
(AUTOCAD_MCP_BACKEND=dxf). Typical flow: autocad_get_status -> autocad_launch_application
(live backend only) -> autocad_create_new_drawing or autocad_open_drawing ->
autocad_pin_document -> drawing tools -> autocad_save_drawing.
Rules: coordinates are [x, y] or [x, y, z] in the drawing's own units (autocad_get_status /
autocad_drawing_summary report them); angles are degrees, counterclockwise. Errors come back as
JSON with a stable `code` and a `recommended_action`. Results of tools that change the drawing
carry `state` (executed / verified / saved) -- `saved: false` means the drawing still needs
autocad_save_drawing. Destructive tools default to dry_run=true: read the plan, then repeat
with dry_run=false. Read-only tools never modify the drawing."""

server = MCPServer(
    name="autocad-mcp",
    title="AutoCAD MCP",
    description="AutoCAD automation over COM, plus a headless DXF backend, with typed tools for "
    "drafting, editing, inspection, residential layouts, QC and output.",
    instructions=INSTRUCTIONS,
    version=__version__,
)

_ENABLED_TOOLSETS = registry.enabled_toolsets()
_MUTATING_KINDS = {"write", "destructive", "external"}


def _backend_label() -> str | None:
    try:
        return session.backend_name()
    except CadError:
        return None


def _with_state(spec: ToolSpec, result):
    if not isinstance(result, dict):
        return result
    backend = _backend_label()
    if backend:
        result.setdefault("backend", backend)
    if spec.kind in _MUTATING_KINDS and "state" not in result:
        dry_run = bool(result.get("dry_run", False))
        result["state"] = {
            "accepted": True,
            "preflight_passed": True,
            "executed": not dry_run,
            "verified": result.get("verified") if not dry_run else False,
            "saved": bool(result.get("saved", False)),
        }
    return result


def cad_tool(*, toolset: str, kind: str, title: str, operation: str | None = None, notes: str = ""):
    def decorate(fn):
        spec = registry.register(
            ToolSpec(name=fn.__name__, toolset=toolset, kind=kind, title=title, operation=operation, notes=notes)
        )

        @functools.wraps(fn)
        def boundary(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:  # every failure leaves as a classified envelope
                log.info("tool %s failed: %s: %s", spec.name, type(exc).__name__, exc)
                raise ToolError(error_text(exc, tool=spec.name, backend=_backend_label())) from exc
            return _with_state(spec, result)

        # What MCP clients call. Returning an is_error CallToolResult (instead of
        # letting ToolError escape) keeps the text a bare JSON envelope: the SDK
        # would otherwise prefix it with "Error executing tool <name>: ".
        # Python callers (tests, other modules) use `boundary`, which raises.
        @functools.wraps(fn)
        def mcp_entry(*args, **kwargs):
            try:
                return boundary(*args, **kwargs)
            except ToolError as exc:
                return CallToolResult(content=[TextContent(type="text", text=str(exc))], is_error=True)

        if spec.toolset in _ENABLED_TOOLSETS:
            server.tool(
                name=spec.name,
                title=title,
                description=inspect.getdoc(fn),
                annotations=ToolAnnotations(**spec.annotations()),
            )(mcp_entry)
        return boundary

    return decorate


def backend():
    return get_backend()


# ======= core: status, launch, capabilities, pinning =======


@cad_tool(toolset="core", kind="read", title="AutoCAD status", operation="get_status")
def autocad_get_status() -> dict:
    """Report the backend this server is pinned to and, for the live backend, whether AutoCAD
    2021+ is installed, running, reachable over COM and a supported release; plus a best-effort
    OpenCode session detection flag and the document pin. Never starts AutoCAD."""
    status = backend().get_status()
    status["opencode"] = detect_opencode()
    status["pin"] = session.pin_state()
    status["units_preset"] = units.preset_name()
    return status


@cad_tool(toolset="core", kind="external", title="Launch AutoCAD", operation="launch_application")
def autocad_launch_application(timeout_seconds: Annotated[float, Field(description='Seconds to wait for AutoCAD to answer COM calls; the executor deadline is 30 s longer than this.')] = 60) -> dict:
    """Launch AutoCAD if not already running, and wait until it answers COM calls.
    Does nothing destructive if AutoCAD is already running; just verifies it.
    Live backend only."""
    result = backend().launch_application(timeout_seconds=timeout_seconds)
    result["verified"] = bool(result.get("connected"))
    return result


@cad_tool(toolset="core", kind="read", title="Server capabilities")
def autocad_get_capabilities() -> dict:
    """Machine-readable description of this server: version, pinned backend, enabled toolsets,
    every registered tool with its side-effect kind and the backends that implement it, the
    configuration in force (units preset, COM timeout, allowed output folders) and COM worker
    statistics. Use it instead of guessing what a backend supports."""
    from backends.com import com_timeout
    from backends.dxf import ezdxf_version
    from core.paths import allowed_dirs

    caps = registry.capability_map()
    return {
        "status": "ok",
        "server_version": __version__,
        "backend": session.backend_name(),
        "toolsets": {name: {"description": desc, "enabled": name in _ENABLED_TOOLSETS}
                     for name, desc in registry.TOOLSETS.items()},
        "tools": caps["tools"],
        "operations": caps["operations"],
        "config": {
            "units_preset": units.preset_name(),
            "units_presets": {k: dict(v) for k, v in units.UNIT_PRESETS.items()},
            "com_timeout_seconds": com_timeout(),
            "output_dir": get_output_dir(),
            "db_path": get_db_path(),
            "allowed_dirs": [str(d) for d in allowed_dirs()],
        },
        "dependencies": {"ezdxf": ezdxf_version()},
        "com_worker": get_executor().stats(),
        "pin": session.pin_state(),
    }


@cad_tool(toolset="core", kind="session", title="Pin the active drawing", operation="active_drawing_identity")
def autocad_pin_document(identity: Annotated[str | None, Field(description="Drawing identity to pin (from autocad_list_drawings); must equal the active drawing's identity.")] = None) -> dict:
    """Pin this session to the active drawing: until autocad_unpin_document, every tool refuses
    (E_DOCUMENT_CHANGED, nothing changed) if a different drawing becomes active -- e.g. the user
    switches drawing tabs mid-job. identity, if given, must equal the active drawing's identity
    (as reported in drawing_identity); otherwise the active drawing is pinned. Saving an unsaved
    drawing changes its identity; pin again after the first save."""
    active = backend().active_drawing_identity()
    if active is None:
        raise CadError("No drawing is open to pin.", code="E_NO_ACTIVE_DOCUMENT")
    if identity is not None and identity != active:
        raise CadError(
            f"{identity!r} is not the active drawing ({active!r}); activate it first.",
            code="E_DOCUMENT_CHANGED",
            details={"requested": identity, "active_document": active},
        )
    result = session.pin_document(active)
    return {"status": "ok", **result, "message": f"Pinned to {active!r}."}


@cad_tool(toolset="core", kind="session", title="Unpin the drawing")
def autocad_unpin_document() -> dict:
    """Remove the document pin set by autocad_pin_document. Tools then act on whichever drawing
    is active, as before pinning."""
    result = session.unpin_document()
    return {"status": "ok", **result, "message": "Unpinned." if result["previous_pin"] else "No pin was set."}


@cad_tool(toolset="core", kind="external", title="Create test drawing (V0.1.0)",
          operation="create_test_drawing_with_line")
def autocad_create_test_drawing_with_line(output_dir: Annotated[str | None, Field(description='Folder to save the test drawing in (default: Documents/AutoCAD MCP Output); created if missing.')] = None) -> dict:
    """Create a new drawing, draw one line from (0,0,0) to (100,100,0), save it as
    mcp_test_<timestamp>.dwg under output_dir (default: Documents/AutoCAD MCP Output),
    and verify the entity and file exist. Requires AutoCAD to already be connected;
    call autocad_get_status / autocad_launch_application first."""
    result = backend().create_test_drawing_with_line(output_dir=output_dir)
    result.update(verified=True, saved=True)
    return result


@cad_tool(toolset="core", kind="write", title="New drawing", operation="create_new_drawing")
def autocad_create_new_drawing(template: Annotated[str | None, Field(description='Template to start from: a .dwt path, or a bare name AutoCAD finds on its template path.')] = None, pin: Annotated[bool, Field(description='Allow creating despite a document pin, moving the pin to the new drawing.')] = False) -> dict:
    """Create a new, unsaved drawing (live: Documents.Add; headless: a new in-memory DXF). Never
    touches disk, so it cannot overwrite a file. template, if given, is a .dwt path (or a bare
    template name AutoCAD finds on its template path). If a document pin is set, this refuses
    unless pin=true, which moves the pin to the new drawing."""
    return backend().create_new_drawing(template=template, pin=pin)


@cad_tool(toolset="core", kind="read", title="List open drawings", operation="list_drawings")
def autocad_list_drawings() -> dict:
    """List open drawings with identity, path, unsaved-changes flag, read-only flag and which one
    is active. Use an identity from here with autocad_activate_drawing / autocad_close_drawing."""
    return backend().list_drawings()


@cad_tool(toolset="core", kind="write", title="Open drawing", operation="open_drawing")
def autocad_open_drawing(path: Annotated[str, Field(description='Path to the drawing file to open (.dwg, .dxf, .dwt or .dws).')], read_only: Annotated[bool, Field(description='Open read-only by default; pass false so the drawing can be edited.')] = True, pin: Annotated[bool, Field(description='Allow opening despite a document pin, moving the pin to the opened drawing.')] = False) -> dict:
    """Open a .dwg/.dxf/.dwt/.dws file (read-only by default -- pass read_only=false to edit it)
    and make it active; an already-open file is just activated. While a document pin is set this
    refuses unless pin=true, which moves the pin to the opened drawing."""
    return backend().open_drawing(path=path, read_only=read_only, pin=pin)


@cad_tool(toolset="core", kind="destructive", title="Save drawing", operation="save_drawing")
def autocad_save_drawing(path: Annotated[str | None, Field(description="Target file for save-as; null saves to the drawing's own file (requires a prior save and read-write access).")] = None, overwrite: Annotated[bool, Field(description='Allow replacing an existing different file; the active drawing itself is never overwritten without it.')] = False, format: Annotated[str, Field(description="'dwg' (binary drawing) or 'dxf' (ASCII exchange).")] = "dwg",
                         version: Annotated[str, Field(description='DWG release tag written into the file: R2000, R2004, R2007, R2010, R2013 or R2018.')] = "R2018") -> dict:
    """Save the active drawing. path=None saves to its own file (it must have been saved before
    and not be read-only). With path: save as that .dwg (or .dxf with format="dxf"); an existing
    different file is only replaced with overwrite=true. Save-as re-points the open drawing at the
    new file (a pin follows it); use autocad_export_dxf to write a copy instead. version: R2000,
    R2004, R2007, R2010, R2013, R2018. Reports the file's size and SHA-256 read back from disk."""
    return backend().save_drawing(path=path, overwrite=overwrite, format=format, version=version)


@cad_tool(toolset="core", kind="destructive", title="Close drawing", operation="close_drawing")
def autocad_close_drawing(identity: Annotated[str | None, Field(description='Identity of the drawing to close (default: the active one); from autocad_list_drawings.')] = None, discard_changes: Annotated[bool, Field(description='Close even when the drawing has unsaved changes.')] = False) -> dict:
    """Close a drawing (default: the active one) without saving. Refuses when it has unsaved
    changes unless discard_changes=true. Closing the pinned drawing removes the pin."""
    return backend().close_drawing(identity=identity, discard_changes=discard_changes)


@cad_tool(toolset="core", kind="write", title="Activate drawing", operation="activate_drawing")
def autocad_activate_drawing(identity: Annotated[str, Field(description='Identity of the open drawing to make active; from autocad_list_drawings.')], pin: Annotated[bool, Field(description='Allow activation despite a document pin, moving the pin.')] = False) -> dict:
    """Make the open drawing with this identity the active one. While a document pin is set this
    refuses unless pin=true, which moves the pin."""
    return backend().activate_drawing(identity=identity, pin=pin)


@cad_tool(toolset="core", kind="write", title="Set drawing units", operation="set_drawing_units")
def autocad_set_drawing_units(preset: Annotated[str, Field(description="Units preset to apply and keep for this session: 'engineering', 'architectural', 'metric_mm', 'metric_m' or 'preserve'.")]) -> dict:
    """Apply a units preset to the active drawing and keep it for this session (drawing tools then
    stop re-applying the AUTOCAD_MCP_UNITS default): engineering (feet + decimal inches, INSUNITS
    inches), architectural (feet + fractional inches), metric_mm (INSUNITS mm), metric_m
    (INSUNITS m), or preserve (stop changing units at all). Reports every variable changed."""
    return backend().set_drawing_units(preset=preset)


# ======= drawing: primitives =======


@cad_tool(toolset="drawing", kind="write", title="Draw line", operation="draw_line")
def autocad_draw_line(start_point: Point, end_point: Point, layer: Layer = None) -> dict:
    """Draw a line between two validated points in the active drawing's
    ModelSpace. Points are [x, y] or [x, y, z]; z defaults to 0."""
    return backend().draw_line(start_point=start_point, end_point=end_point, layer=layer)


@cad_tool(toolset="drawing", kind="write", title="Draw polyline", operation="draw_polyline")
def autocad_draw_polyline(points: Points, closed: Annotated[bool, Field(description='Close the polyline from its last vertex back to the first.')] = False, layer: Layer = None) -> dict:
    """Draw a polyline through an ordered list of >=2 points ([x, y] or
    [x, y, z], z defaults to 0), optionally closed, as an AcDb3dPolyline."""
    return backend().draw_polyline(points=points, closed=closed, layer=layer)


@cad_tool(toolset="drawing", kind="write", title="Draw rectangle", operation="draw_rectangle")
def autocad_draw_rectangle(
    corner1: Annotated[list[float] | None, Field(description='One corner of the rectangle, [x, y] or [x, y, z]; used together with corner2 (the opposite corner, same z-plane).')] = None,
    corner2: Annotated[list[float] | None, Field(description="Opposite corner of the rectangle, [x, y] or [x, y, z]; must share corner1's z-plane.")] = None,
    base_point: Annotated[list[float] | None, Field(description='Lower-left corner, [x, y] or [x, y, z]; used together with width and height.')] = None,
    width: Annotated[float | None, Field(description='Rectangle width in drawing units (with base_point); must be positive.')] = None,
    height: Annotated[float | None, Field(description='Rectangle height in drawing units (with base_point); must be positive.')] = None,
    layer: Layer = None,
) -> dict:
    """Draw an axis-aligned rectangle (as a closed polyline). Give exactly
    one of: corner1 and corner2 (opposite corners, same z-plane), or
    base_point with positive width and height."""
    return backend().draw_rectangle(
        corner1=corner1, corner2=corner2, base_point=base_point, width=width, height=height, layer=layer
    )


@cad_tool(toolset="drawing", kind="write", title="Draw circle", operation="draw_circle")
def autocad_draw_circle(center: Point, radius: Annotated[float, Field(description='Circle radius in drawing units; must be positive.')], layer: Layer = None) -> dict:
    """Draw a circle at center ([x, y] or [x, y, z]) with a positive radius."""
    return backend().draw_circle(center=center, radius=radius, layer=layer)


@cad_tool(toolset="drawing", kind="write", title="Draw text", operation="draw_text")
def autocad_draw_text(
    text: Annotated[str, Field(description='Text string to draw.')],
    insertion_point: Point,
    height: Annotated[float, Field(description='Text height in drawing units; must be positive.')],
    rotation_degrees: Annotated[float, Field(description='Rotation in degrees counterclockwise (AutoCAD convention).')] = 0.0,
    layer: Layer = None,
) -> dict:
    """Add single-line text at insertion_point with a positive height and an
    optional rotation in degrees (counterclockwise, viewed from +Z)."""
    return backend().draw_text(
        text=text, insertion_point=insertion_point, height=height, rotation_degrees=rotation_degrees, layer=layer
    )


@cad_tool(toolset="drawing", kind="write", title="Draw arc", operation="draw_arc")
def autocad_draw_arc(center: Point, radius: Annotated[float, Field(description='Arc radius in drawing units; must be positive.')], start_angle_degrees: Annotated[float, Field(description='Start angle in degrees from +X, counterclockwise (AutoCAD convention).')], end_angle_degrees: Annotated[float, Field(description='End angle in degrees from +X, counterclockwise; the arc runs from start to end.')],
                     layer: Layer = None) -> dict:
    """Draw a counterclockwise arc around center from start_angle_degrees to end_angle_degrees
    (degrees from +X). Reports the angles and arc length read back."""
    return backend().draw_arc(center=center, radius=radius, start_angle_degrees=start_angle_degrees,
                              end_angle_degrees=end_angle_degrees, layer=layer)


@cad_tool(toolset="drawing", kind="write", title="Draw MTEXT", operation="draw_mtext")
def autocad_draw_mtext(text: Annotated[str, Field(description="Text string; '\\P' starts a new paragraph.")], insertion_point: Point, height: Annotated[float, Field(description='Text height in drawing units; must be positive.')], width: Annotated[float, Field(description='Wrapping width in drawing units; 0 means no wrapping.')] = 0.0,
                       rotation_degrees: Annotated[float, Field(description='Rotation in degrees counterclockwise.')] = 0.0, layer: Layer = None) -> dict:
    """Add multiline text (top-left at insertion_point). width 0 = no wrapping; \\P in text starts a
    new paragraph."""
    return backend().draw_mtext(text=text, insertion_point=insertion_point, height=height, width=width,
                                rotation_degrees=rotation_degrees, layer=layer)


# ======= layers =======


@cad_tool(toolset="layers", kind="read", title="List layers", operation="list_layers")
def autocad_list_layers() -> dict:
    """List every layer with on/frozen/locked state, color, linetype, lineweight, plottable flag,
    and which one is current."""
    return backend().list_layers()


@cad_tool(toolset="layers", kind="write", title="Set layer properties", operation="set_layer_properties")
def autocad_set_layer_properties(name: Annotated[str, Field(description='Name of the existing layer to change.')], on: Annotated[bool | None, Field(description='Turn the layer on (true) or off (false); null leaves the current state.')] = None, frozen: Annotated[bool | None, Field(description='Freeze (true) or thaw (false); null leaves the current state.')] = None,
                                 locked: Annotated[bool | None, Field(description='Lock (true) or unlock (false); null leaves the current state.')] = None, color_index: Annotated[int | None, Field(description='ACI colour index 0-255 (0 ByBlock, 256 ByLayer); null leaves it.')] = None,
                                 linetype: Annotated[str | None, Field(description='Linetype name; loaded from acad.lin/acadiso.lin if not already present; null leaves it.')] = None, lineweight: Annotated[int | None, Field(description='Lineweight in hundredths of a millimetre (-3 Default, 25 = 0.25 mm); null leaves it.')] = None,
                                 plottable: Annotated[bool | None, Field(description='Plot the layer (true) or not (false); null leaves it.')] = None) -> dict:
    """Change only the given properties of an existing layer and read them back. lineweight is in
    hundredths of a millimetre (25 = 0.25 mm, -3 = Default). A linetype that isn't loaded is loaded
    from acad.lin / acadiso.lin. The current layer cannot be frozen."""
    return backend().set_layer_properties(name=name, on=on, frozen=frozen, locked=locked,
                                          color_index=color_index, linetype=linetype, lineweight=lineweight,
                                          plottable=plottable)


@cad_tool(toolset="layers", kind="write", title="Create layer", operation="create_layer")
def autocad_create_layer(name: Annotated[str, Field(description='Name of the layer to create; an existing layer is updated, not replaced.')], color_index: Annotated[int | None, Field(description='ACI colour index 0-255 to set; null leaves the layer untouched.')] = None, linetype: Annotated[str | None, Field(description='Linetype to set; null leaves the layer untouched.')] = None) -> dict:
    """Create a layer if it doesn't exist. color_index (0-255) and linetype,
    when given, update that property on an existing layer; every other
    layer property (locked, frozen, on/off, ...) is left untouched."""
    return backend().create_layer(name=name, color_index=color_index, linetype=linetype)


@cad_tool(toolset="layers", kind="write", title="Ensure standard layer", operation="ensure_layer")
def autocad_ensure_layer(name: Annotated[str, Field(description="Layer name; a name matching the architectural standard (A-WALL, A-DOOR, ...) gets that standard's colour/linetype unless overridden.")], color_index: Annotated[int | None, Field(description='Explicit ACI colour index 0-255; always overrides the standard.')] = None, linetype: Annotated[str | None, Field(description='Explicit linetype name; always overrides the standard.')] = None) -> dict:
    """Same as autocad_create_layer, except a name matching the
    architectural layer standard (A-WALL, A-WALL-EXT, A-WALL-INT, A-DOOR, A-GLAZ, A-ANNO,
    A-TEXT, A-DIM, ...) falls back to that standard's color_index/linetype when not given
    explicitly. An explicit color_index/linetype always overrides it."""
    return backend().ensure_layer(name=name, color_index=color_index, linetype=linetype)


# ======= editing =======


@cad_tool(toolset="editing", kind="write", title="Move entity", operation="move_entity")
def autocad_move_entity(handle: Handle, displacement: Annotated[list[float], Field(description='Translation vector [dx, dy, dz] in drawing units.')]) -> dict:
    """Move the entity with this handle by a validated [dx, dy, dz] vector."""
    return backend().move_entity(handle=handle, displacement=displacement)


@cad_tool(toolset="editing", kind="write", title="Rotate entity", operation="rotate_entity")
def autocad_rotate_entity(handle: Handle, base_point: Point, angle_degrees: Annotated[float, Field(description='Rotation in degrees counterclockwise about base_point.')]) -> dict:
    """Rotate the entity with this handle about base_point by angle_degrees
    (counterclockwise-positive, viewed from +Z -- AutoCAD's own convention)."""
    return backend().rotate_entity(handle=handle, base_point=base_point, angle_degrees=angle_degrees)


@cad_tool(toolset="editing", kind="write", title="Copy entity", operation="copy_entity")
def autocad_copy_entity(handle: Handle, displacement: Annotated[list[float], Field(description='Offset [dx, dy, dz] of the copy from the original, in drawing units.')]) -> dict:
    """Copy the entity with this handle, offsetting the copy by a validated
    [dx, dy, dz] vector. Returns the new entity's handle."""
    return backend().copy_entity(handle=handle, displacement=displacement)


@cad_tool(toolset="editing", kind="write", title="Highlight entity", operation="highlight_entity")
def autocad_highlight_entity(handle: Handle, method: Annotated[str, Field(description="'temporary' uses AutoCAD's native Highlight flag (not saved to the DWG); 'persistent' sets entity.Color.")] = "temporary", color: Annotated[int, Field(description="ACI colour index 0-255 used by method='persistent'.")] = 1, clear: Annotated[bool, Field(description="Turn a temporary highlight back off (method='temporary').")] = False) -> dict:
    """Highlight an entity. method="temporary" uses AutoCAD's native
    Highlight() flag (a visual-only state, not saved to the DWG, that never
    touches the entity's Color property) -- pass clear=True to turn it back
    off. method="persistent" sets entity.Color (0-255) and does not revert."""
    return backend().highlight_entity(handle=handle, method=method, color=color, clear=clear)


@cad_tool(toolset="editing", kind="write", title="Highlight matching text", operation="highlight_text_matches")
def autocad_highlight_text_matches(
    pattern: Annotated[str, Field(description='Literal substring matched against the text of TEXT/MTEXT entities.')],
    use_regex: Annotated[bool, Field(description='Treat pattern as a regular expression instead of a literal substring.')] = False,
    method: Annotated[str, Field(description="Highlight mode: 'temporary' (native Highlight flag) or 'persistent' (sets entity.Color).")] = "temporary",
    color: Annotated[int, Field(description="ACI colour index 0-255 for method='persistent'.")] = 1,
    clear: Annotated[bool, Field(description='Also clear existing temporary highlights on the matched entities.')] = False,
    limit: Annotated[int, Field(description='Maximum number of matches to list (every match is highlighted).')] = 500,
) -> dict:
    """Find TEXT/MTEXT entities matching pattern (literal substring, or a
    regex if use_regex=True) and highlight them the same way as
    autocad_highlight_entity. Never modifies the matched entities' text.
    Every match is highlighted; the returned list holds at most `limit` of them."""
    return backend().highlight_text_matches(
        pattern=pattern, use_regex=use_regex, method=method, color=color, clear=clear, limit=limit
    )


@cad_tool(toolset="editing", kind="write", title="Scale entity", operation="scale_entity")
def autocad_scale_entity(handle: Handle, base_point: Point, factor: Annotated[float, Field(description='Uniform scale factor; must be positive.')]) -> dict:
    """Scale the entity uniformly about base_point by a positive factor; verifies the extents
    changed by that factor."""
    return backend().scale_entity(handle=handle, base_point=base_point, factor=factor)


@cad_tool(toolset="editing", kind="write", title="Mirror entity", operation="mirror_entity")
def autocad_mirror_entity(handle: Handle, axis_start: Point, axis_end: Point,
                          keep_original: Annotated[bool, Field(description='Delete the original entity after mirroring when false.')] = True) -> dict:
    """Mirror the entity across the line axis_start-axis_end. Returns the mirrored copy's handle;
    keep_original=false deletes the source afterwards."""
    return backend().mirror_entity(handle=handle, axis_start=axis_start, axis_end=axis_end,
                                   keep_original=keep_original)


@cad_tool(toolset="editing", kind="write", title="Offset curve", operation="offset_entity")
def autocad_offset_entity(handle: Handle, distance: Annotated[float, Field(description='Offset distance in drawing units; the sign picks the side.')]) -> dict:
    """Offset a curve (line, arc, circle, polyline, ellipse, spline) by distance; the sign picks the
    side. Returns the new handles."""
    return backend().offset_entity(handle=handle, distance=distance)


@cad_tool(toolset="editing", kind="write", title="Rectangular array", operation="array_rectangular")
def autocad_array_rectangular(handle: Handle, rows: Annotated[int, Field(description='Number of rows (stacked along Y).')], columns: Annotated[int, Field(description='Number of columns (stacked along X).')], row_spacing: Annotated[float, Field(description='Row spacing in drawing units.')],
                              column_spacing: Annotated[float, Field(description='Column spacing in drawing units.')]) -> dict:
    """Copy the entity into a rows x columns grid (row_spacing along Y, column_spacing along X; the
    original is the first cell). Returns the rows*columns-1 new handles."""
    return backend().array_rectangular(handle=handle, rows=rows, columns=columns, row_spacing=row_spacing,
                                       column_spacing=column_spacing)


@cad_tool(toolset="editing", kind="destructive", title="Delete entities", operation="delete_entities")
def autocad_delete_entities(handles: Handles, dry_run: Annotated[bool, Field(description='true (the default) only lists what would be deleted and changes nothing; false deletes.')] = True) -> dict:
    """Delete entities by handle. dry_run=true (the default) only lists what would be deleted and
    changes nothing; call again with dry_run=false to delete. Verifies each deleted handle no longer
    resolves. Ctrl+Z in AutoCAD can undo it."""
    return backend().delete_entities(handles=handles, dry_run=dry_run)


@cad_tool(toolset="editing", kind="write", title="Set entity properties", operation="set_entity_properties")
def autocad_set_entity_properties(handles: Handles, layer: Layer = None, color_index: Annotated[int | None, Field(description='ACI colour index 0-256 (0 ByBlock, 256 ByLayer); null leaves it.')] = None,
                                  linetype: Annotated[str | None, Field(description='Linetype name; null leaves it.')] = None, lineweight: Annotated[int | None, Field(description='Lineweight in hundredths of a millimetre (-1 ByLayer); null leaves it.')] = None) -> dict:
    """Set layer / color (ACI 0-256: 0 ByBlock, 256 ByLayer) / linetype / lineweight (hundredths of
    mm, -1 ByLayer) on one or more entities and read them back. A missing layer is created."""
    return backend().set_entity_properties(handles=handles, layer=layer, color_index=color_index,
                                           linetype=linetype, lineweight=lineweight)


# ======= query: inspection =======


@cad_tool(toolset="query", kind="read", title="Drawing summary", operation="drawing_summary")
def autocad_drawing_summary(max_entities: Annotated[int, Field(description='Read at most this many model-space entities (larger drawings are truncated, and the result says so).')] = 20000) -> dict:
    """Compact overview of the active drawing: identity, saved/unsaved state, units (INSUNITS,
    LUNITS, imperial/metric), extents, entity counts by type and by layer, layers, block
    definitions and layouts. Reads at most max_entities model-space entities (truncated says if
    more exist). Start here before editing an unfamiliar drawing."""
    return backend().drawing_summary(max_entities=max_entities)


@cad_tool(toolset="query", kind="read", title="List entities", operation="list_entities")
def autocad_list_entities(entity_types: Annotated[list[str] | None, Field(description='DXF type names to include (LINE, LWPOLYLINE, CIRCLE, TEXT, MTEXT, ...); null = all types.')] = None, layers: Annotated[list[str] | None, Field(description='Layer names to include; null = all layers.')] = None,
                          bbox: Annotated[list[list[float]] | None, Field(description='Filter window [[xmin, ymin], [xmax, ymax]] in drawing units; only entities lying inside it are returned.')] = None, offset: Annotated[int, Field(description='Skip this many matches (combine with the returned next_offset to page).')] = 0, limit: Annotated[int, Field(description='Return at most this many rows.')] = 100,
                          include_bbox: Annotated[bool, Field(description="Include each entity's bounding box in the result rows.")] = False) -> dict:
    """Page through model-space entities as {handle, type, layer}, optionally filtered by DXF type
    names (LINE, LWPOLYLINE, POLYLINE3D, CIRCLE, ARC, TEXT, MTEXT, INSERT, HATCH, DIMENSION, ...),
    layer names, and a bbox window [[xmin, ymin], [xmax, ymax]] the entity must lie inside. Use
    offset/next_offset to page; total counts every match."""
    return backend().list_entities(entity_types=entity_types, layers=layers, bbox=bbox, offset=offset,
                                   limit=limit, include_bbox=include_bbox)


@cad_tool(toolset="query", kind="read", title="Get entity", operation="get_entity")
def autocad_get_entity(handle: Handle) -> dict:
    """Full detail of one entity: type, layer, color, linetype, lineweight, geometry (points,
    center/radius, angles in degrees, text, block name and attributes, hatch pattern and area,
    dimension measurement), length/area where AutoCAD reports them, and bounding box."""
    return backend().get_entity(handle=handle)


# ======= annotation =======


@cad_tool(toolset="annotation", kind="write", title="Add dimension", operation="add_dimension")
def autocad_add_dimension(kind: Annotated[str, Field(description="'aligned' measures along the line through the two points; 'linear' measures horizontally/vertically along rotation_degrees.")], first_point: Point, second_point: Point,
                          dimension_line_point: Point, rotation_degrees: Annotated[float, Field(description="Degrees counterclockwise; used with kind='linear'.")] = 0.0,
                          text_override: Annotated[str | None, Field(description='Custom dimension text; null uses the measured value.')] = None, layer: Layer = None) -> dict:
    """Add a dimension between two points using the current dimension style. kind="aligned"
    measures along the points; kind="linear" measures along rotation_degrees (0 horizontal, 90
    vertical). The dimension line passes through dimension_line_point. Verifies the measurement
    AutoCAD reports equals the geometry."""
    return backend().add_dimension(kind=kind, first_point=first_point, second_point=second_point,
                                   dimension_line_point=dimension_line_point, rotation_degrees=rotation_degrees,
                                   text_override=text_override, layer=layer)


@cad_tool(toolset="annotation", kind="write", title="Add hatch", operation="add_hatch")
def autocad_add_hatch(boundary_handles: Annotated[list[str] | None, Field(description='Handles of an already-closed boundary (curves or a closed polyline).')] = None, boundary_points: Annotated[list[list[float]] | None, Field(description='Polygon vertices [x, y] or [x, y, z]; a boundary polyline is drawn for them.')] = None,
                      pattern: Annotated[str, Field(description='Predefined hatch pattern name (ANSI31, SOLID, AR-CONC, ...).')] = "ANSI31", scale: Annotated[float, Field(description='Pattern scale; must be positive.')] = 1.0, angle_degrees: Annotated[float, Field(description='Pattern rotation in degrees.')] = 0.0,
                      layer: Layer = None, keep_boundary: Annotated[bool, Field(description='Keep the boundary polyline drawn for boundary_points (true by default).')] = True) -> dict:
    """Hatch one closed area: give boundary_handles (closed curves already drawn) or boundary_points
    (a polygon; a boundary polyline is drawn and kept unless keep_boundary=false). pattern is a
    predefined pattern name (ANSI31, SOLID, AR-CONC, ...). Reports the hatched area and verifies the
    pattern read back."""
    return backend().add_hatch(boundary_handles=boundary_handles, boundary_points=boundary_points,
                               pattern=pattern, scale=scale, angle_degrees=angle_degrees, layer=layer,
                               keep_boundary=keep_boundary)


# ======= blocks =======


@cad_tool(toolset="blocks", kind="read", title="List blocks", operation="list_blocks")
def autocad_list_blocks(include_anonymous: Annotated[bool, Field(description='Also list anonymous block definitions (created internally by AutoCAD).')] = False) -> dict:
    """List block definitions (not layouts) with entity count, attribute tags, and xref status."""
    return backend().list_blocks(include_anonymous=include_anonymous)


@cad_tool(toolset="blocks", kind="write", title="Insert block", operation="insert_block")
def autocad_insert_block(name: Annotated[str, Field(description='Block definition name (must already exist in the drawing).')], insertion_point: Point, scale: Annotated[float, Field(description='Insertion scale; must be positive.')] = 1.0,
                         rotation_degrees: Annotated[float, Field(description='Insertion rotation in degrees counterclockwise.')] = 0.0, layer: Layer = None,
                         attributes: Annotated[dict[str, str] | None, Field(description='Attribute values {TAG: value}; unknown tags are rejected before anything is inserted.')] = None) -> dict:
    """Insert a block already defined in the drawing, optionally filling attributes {TAG: value}.
    Unknown tags are rejected before anything is inserted; values are read back."""
    return backend().insert_block(name=name, insertion_point=insertion_point, scale=scale,
                                  rotation_degrees=rotation_degrees, layer=layer, attributes=attributes)


@cad_tool(toolset="blocks", kind="read", title="Get block attributes", operation="get_block_attributes")
def autocad_get_block_attributes(handle: Handle) -> dict:
    """List the attributes (tag, value, handle) of a block reference."""
    return backend().get_block_attributes(handle=handle)


@cad_tool(toolset="blocks", kind="write", title="Set block attributes", operation="set_block_attributes")
def autocad_set_block_attributes(handle: Handle, values: Annotated[dict[str, str], Field(description='Attribute values {TAG: text} to set; unknown tags are rejected.')]) -> dict:
    """Update attribute values {TAG: text} on a block reference and read them back. Unknown tags
    are rejected before any change."""
    return backend().set_block_attributes(handle=handle, values=values)


# ======= output =======


@cad_tool(toolset="output", kind="read", title="List layouts", operation="list_layouts")
def autocad_list_layouts() -> dict:
    """List layouts (Model and paper-space sheets) with plot device, paper, plot style and which
    one is current."""
    return backend().list_layouts()


@cad_tool(toolset="output", kind="external", title="Export DXF copy", operation="export_dxf")
def autocad_export_dxf(path: Annotated[str, Field(description='Destination .dxf path (absolute).')], overwrite: Annotated[bool, Field(description='Allow replacing an existing file; the open drawing itself is never renamed (a copy is written).')] = False) -> dict:
    """Write a DXF copy of the active drawing to path (.dxf) without renaming or re-pointing the open
    drawing (unlike save-as). Existing files are replaced only with overwrite=true, and only after
    the new file was written. Reports size and SHA-256 read back from disk."""
    return backend().export_dxf(path=path, overwrite=overwrite)


@cad_tool(toolset="output", kind="external", title="Plot to PDF", operation="plot_pdf")
def autocad_plot_pdf(path: Annotated[str, Field(description='Destination .pdf path.')], layout: Annotated[str | None, Field(description='Layout name to plot; null plots model space fitted to the paper extents.')] = None, paper: Annotated[str | None, Field(description="Canonical media name or a unique part of one (e.g. 'ISO_full_bleed_A3').")] = None,
                     plot_style: Annotated[str | None, Field(description="Plot style table name (e.g. 'monochrome.ctb').")] = None, overwrite: Annotated[bool, Field(description='Allow replacing an existing file.')] = False) -> dict:
    """Plot to a PDF with AutoCAD's 'DWG To PDF.pc3'. layout=None plots model space to its extents,
    fitted to the paper; a layout name plots that sheet at 1:1. paper is a canonical media name or a
    unique part of one (e.g. 'ISO_full_bleed_A3'); plot_style e.g. 'monochrome.ctb'. The layout's
    plot settings and BACKGROUNDPLOT are restored afterwards. Verifies the PDF on disk and reports
    its paper size in mm."""
    return backend().plot_pdf(path=path, layout=layout, paper=paper, plot_style=plot_style, overwrite=overwrite)


# ======= query: analysis and database =======


@cad_tool(toolset="query", kind="read", title="Scan entities to database", operation="scan_all_entities",
          notes="writes the server's SQLite cache, never the drawing")
def autocad_scan_all_entities() -> dict:
    """Scan top-level ModelSpace entities (lines, circles, polylines,
    text/mtext -- not block references or PaperSpace) and replace this
    drawing's snapshot in the local SQLite database (other drawings'
    records are untouched; rescanning is idempotent). Never modifies the drawing."""
    return backend().scan_all_entities()


@cad_tool(toolset="query", kind="read", title="Count text matches", operation="count_text_patterns")
def autocad_count_text_patterns(pattern: Annotated[str, Field(description='Literal substring matched against the text of TEXT/MTEXT entities.')], use_regex: Annotated[bool, Field(description='Treat pattern as a regular expression instead of a literal substring.')] = False, limit: Annotated[int, Field(description='Maximum number of matches to list.')] = 500) -> dict:
    """Count TEXT/MTEXT entities in the active drawing whose text matches
    pattern: a literal substring by default, or a regex if use_regex=True.
    match_count is the full count; at most `limit` matches are listed."""
    return backend().count_text_patterns(pattern=pattern, use_regex=use_regex, limit=limit)


@cad_tool(toolset="query", kind="read", title="Read-only SQL over scans")
def autocad_execute_query(query: Annotated[str, Field(description='One read-only SELECT statement (a WITH clause is allowed); values belong in params, never inline.')], params: Annotated[list | None, Field(description='Bound parameters for ? placeholders in the query (strings or numbers).')] = None, limit: Annotated[int, Field(description='Maximum rows to return (1 to 100000).')] = 1000) -> dict:
    """Run one read-only SELECT (optionally with a WITH clause) against the
    scanned-entities database. Writes, DDL, PRAGMA, and multi-statement
    input are rejected; use params for a parameterized query (never string-
    format user values into the query text). At most `limit` rows are returned;
    `truncated` says whether more matched."""
    limit = validate_limit(limit, default=1000, maximum=100000)
    result = db.execute_readonly_query(get_db_path(), query, params=params, max_rows=limit)
    return {
        "status": "ok",
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "truncated": result.truncated,
    }


@cad_tool(toolset="editing", kind="write", title="Query and highlight", operation="query_and_highlight")
def autocad_query_and_highlight(
    query: Annotated[str, Field(description="Read-only SELECT whose result set includes a 'handle' column (same rules as autocad_execute_query).")],
    params: Annotated[list | None, Field(description='Bound parameters for ? placeholders.')] = None,
    method: Annotated[str, Field(description="'temporary' (native Highlight flag) or 'persistent' (sets entity.Color).")] = "temporary",
    color: Annotated[int, Field(description="ACI colour index 0-255 for method='persistent'.")] = 1,
    clear: Annotated[bool, Field(description='Also clear existing temporary highlights.')] = False,
) -> dict:
    """Run a read-only query (same rules as autocad_execute_query) whose
    result set includes a 'handle' column, then highlight every matching
    entity the same way as autocad_highlight_entity. Stale handles (entity
    deleted since the last scan) are reported in not_found, not raised."""
    return backend().query_and_highlight(query=query, params=params, method=method, color=color, clear=clear)


# ======= architecture =======


@cad_tool(toolset="architecture", kind="write", title="Draw wall", operation="draw_wall")
def autocad_draw_wall(
    start_point: Point,
    end_point: Point,
    thickness: Annotated[float | None, Field(description='Wall thickness in drawing units; null uses the standard exterior (9 in / 230 mm).')] = None,
    layer: LayerName = "A-WALL",
) -> dict:
    """Draw a wall as a closed double-line outline (4-point polyline)
    centered on start_point-end_point, offset by thickness/2 on each side.
    Coordinates and thickness are in the drawing's units. thickness defaults to
    the standard exterior wall for those units (9 in in inch drawings -- the
    V0.2.x default -- or 230 mm in millimetre drawings). Creates the layer via
    autocad_ensure_layer if it doesn't already exist."""
    return backend().draw_wall(start_point=start_point, end_point=end_point, thickness=thickness, layer=layer)


@cad_tool(toolset="architecture", kind="write", title="Generate 2x3 floor plan",
          operation="generate_2d_floor_plan")
def autocad_generate_2d_floor_plan(
    width_ft: Annotated[float, Field(description='Footprint width in feet; must be positive.')] = 24.0,
    length_ft: Annotated[float, Field(description='Footprint length in feet; must be positive.')] = 30.0,
    units: Annotated[str, Field(description="'INCHES' draws the plan in inches (default); 'FEET' treats room bounds as feet.")] = "INCHES",
    rooms_config: Annotated[list[dict] | None, Field(description='Room overrides [{name, width, depth}] replacing the default 2x3 room grid.')] = None,
    dry_run: Annotated[bool, Field(description='Plan and report the entities without drawing anything.')] = False,
) -> dict:
    """Generate a complete residential floor plan in one call: 9"
    exterior walls, 4.5" interior partitions splitting the footprint into a
    fixed 2x3 room grid (Living Room, Kitchen, Bath, 2 Bedrooms by default --
    override with rooms_config), a 36" main entry door and a 30" interior
    door per room, a 48" window per room touching an exterior wall, and an
    MTEXT room label per room. width_ft/length_ft is the footprint in feet;
    drawing happens in inches, matching the Engineering units preset applied
    by default (in a millimetre drawing the same plan is drawn converted to mm).
    units ("INCHES" or "FEET") adds room bounds in feet when "FEET". dry_run=true
    returns the planned entities without drawing anything."""
    return backend().generate_2d_floor_plan(
        width_ft=width_ft, length_ft=length_ft, units=units, rooms_config=rooms_config, dry_run=dry_run
    )


def _plan_result(kind: str, outcome, dry_run: bool, *, extra: dict | None = None) -> dict:
    """Common result for plan-based generators (both backends)."""
    (plan, handles, identity, code), notices = outcome
    result = {
        "status": "ok",
        "generator": kind,
        "dry_run": dry_run,
        "drawing_identity": identity,
        "drawing_unit": units.describe(code),
        "entity_count": len(plan.primitives),
        "counts_by_layer": plan.summary(max_primitives=0)["counts_by_layer"],
        **(extra or {}),
    }
    if dry_run:
        result["plan"] = plan.summary()
        result["message"] = f"Dry run: {len(plan.primitives)} entities would be drawn; nothing was changed."
    else:
        result["handles"] = handles
        result.update(verified=True, verification="modelspace_count_grew_by_planned_entity_count",
                      message=f"Drew {len(plan.primitives)} entities.")
    if notices:
        result["notices"] = notices
    return result


def _origin(origin):
    if origin is None:
        return (0.0, 0.0)
    from utils import geometry

    point = geometry.validate_point_2d_or_3d(origin, "origin")
    return (point[0], point[1])


@cad_tool(toolset="architecture", kind="write", title="Floor plan from rooms", operation="emit_plan")
def autocad_generate_floor_plan(
    rooms: Annotated[list[dict], Field(description='Rooms [{name, x, y, width, depth}] measured to wall centrelines in `unit`; rooms must not overlap.')],
    unit: Annotated[str, Field(description="Unit for every measurement here: 'ft', 'in', 'm' or 'mm'.")] = "ft",
    exterior_wall: Annotated[float | None, Field(description='Exterior wall thickness in `unit`; null = 9 in (imperial) or 230 mm (metric).')] = None,
    interior_wall: Annotated[float | None, Field(description='Interior wall thickness in `unit`; null = 4.5 in (imperial) or 115 mm (metric).')] = None,
    doors: Annotated[list[dict] | None, Field(description='Door specs [{between: [roomA, roomB], width?, position? 0-1}]; null connects every room to the entry room.')] = None,
    windows: Annotated[str, Field(description="'auto' places one window per room on its longest outside wall; 'none' skips windows.")] = "auto",
    entry_room: Annotated[str | None, Field(description='Room receiving the main door (default: the first room).')] = None,
    door_width: Annotated[float | None, Field(description='Interior door width in `unit`; null = 30 in (imperial) or 760 mm (metric).')] = None,
    main_door_width: Annotated[float | None, Field(description='Main entrance door width in `unit`; null = 36 in (imperial) or 915 mm (metric).')] = None,
    window_width: Annotated[float | None, Field(description='Window width in `unit`; null = 48 in (imperial) or 1220 mm (metric).')] = None,
    label_height: Annotated[float | None, Field(description='Room label text height in `unit`; null = the standard for these units.')] = None,
    dimensions: Annotated[bool, Field(description='Add overall dimension chains around the footprint.')] = True,
    origin: Annotated[list[float] | None, Field(description='Plan origin [x, y] in drawing units; null = (0, 0).')] = None,
    dry_run: Annotated[bool, Field(description='Show the plan and schedules without drawing anything.')] = False,
) -> dict:
    """Draw a residential floor plan from explicit rooms. rooms: [{name, x, y, width, depth}] in
    `unit` (ft, in, m, mm), measured to wall centrelines; rooms must not overlap and may form any
    rectilinear footprint. Exterior walls follow the outline, interior walls the shared edges
    (defaults 9"/4.5" or 230/115 mm, override with exterior_wall/interior_wall in `unit`). Doors:
    omit to connect every room to the entry room (entry_room, default the first) through shared
    walls, or give [{between: [roomA, roomB], width?, position? 0-1}]; a main door goes on the entry
    room's outside wall. windows="auto" puts one per room on its longest outside wall, "none" skips
    them. Labels show the clear (net) area. Returns room, door and window schedules. dry_run=true
    shows the plan without drawing. Drafting aid, not a design check."""
    from domain import architecture

    unit_code = units.unit_code(unit)
    point = _origin(origin)

    def build(code):
        return architecture.plan_room_floor_plan(
            rooms, unit_code, code, exterior_wall=exterior_wall, interior_wall=interior_wall, doors=doors,
            windows=windows, entry_room=entry_room, door_width=door_width, main_door_width=main_door_width,
            window_width=window_width, label_height=label_height, dimensions=dimensions, origin=point)

    build(unit_code)  # validate everything before touching the drawing
    outcome = backend().emit_plan(build, dry_run=dry_run)
    meta = outcome[0][0].meta
    return _plan_result("floor_plan", outcome, dry_run, extra={
        "rooms": meta["rooms"], "doors": [{k: v for k, v in d.items() if k != "tag"} for d in meta["doors"]],
        "windows": [{k: v for k, v in w.items() if k != "tag"} for w in meta["windows"]],
        "walls": meta["walls"], "unreachable_rooms": meta["unreachable_rooms"]})


@cad_tool(toolset="architecture", kind="write", title="Structural grid", operation="emit_plan")
def autocad_draw_structural_grid(
    x_spacings: Annotated[list[float], Field(description='Bay widths left to right in `unit` (at least one value).')],
    y_spacings: Annotated[list[float], Field(description='Bay depths bottom to top in `unit`.')],
    unit: Annotated[str, Field(description="'m', 'mm', 'ft' or 'in'.")] = "m",
    origin: Annotated[list[float] | None, Field(description='Grid origin [x, y]; null = (0, 0).')] = None,
    extension: Annotated[float | None, Field(description='Extra length the grid lines extend beyond the outer lines, in `unit`; null = auto.')] = None,
    bubble_diameter: Annotated[float | None, Field(description='Diameter of the grid-line bubbles, in `unit`; null = auto.')] = None,
    text_height: Annotated[float | None, Field(description='Bubble label text height in `unit`; null = the standard for these units.')] = None,
    column_size: Annotated[list[float] | None, Field(description='Column mark [width, depth] in `unit` at every grid intersection; null skips the marks.')] = None,
    skip_letters: Annotated[bool, Field(description='Skip the letters I and O in grid line labels (true by default).')] = True,
    dimensions: Annotated[bool, Field(description='Add bay and overall dimensions between the grid lines.')] = True,
    dry_run: Annotated[bool, Field(description='Plan and report without drawing.')] = False,
) -> dict:
    """Draw a column grid: x_spacings are bay widths left to right (lines numbered 1, 2, 3...),
    y_spacings bay depths bottom to top (lettered A, B, C...; I and O skipped unless
    skip_letters=false), in `unit`. Lines (layer S-GRID, CENTER linetype) end in labelled bubbles;
    column_size [width, depth] adds a filled column mark at every intersection; bay and overall
    dimensions are added. Drafting of a chosen grid, not structural design."""
    from domain import architecture

    unit_code = units.unit_code(unit)
    point = _origin(origin)

    def build(code):
        return architecture.plan_grid(x_spacings, y_spacings, unit_code, code, origin=point, extension=extension,
                               bubble_diameter=bubble_diameter, text_height=text_height, column_size=column_size,
                               skip_letters=skip_letters, dimensions=dimensions)

    build(unit_code)
    outcome = backend().emit_plan(build, dry_run=dry_run)
    meta = outcome[0][0].meta
    return _plan_result("structural_grid", outcome, dry_run, extra={k: meta[k] for k in ("x_lines", "y_lines",
                                                                                          "columns", "overall")})


@cad_tool(toolset="architecture", kind="read", title="Design a stair")
def autocad_design_stair(
    floor_to_floor: Annotated[float, Field(description='Total rise in `unit`; must be positive.')],
    unit: Annotated[str, Field(description="'m', 'mm', 'ft' or 'in'.")] = "mm",
    max_riser: Annotated[float | None, Field(description='Maximum riser height in `unit`; null = 190 mm equivalent.')] = None,
    min_tread: Annotated[float | None, Field(description='Minimum tread depth in `unit`; null = 250 mm equivalent.')] = None,
    tread: Annotated[float | None, Field(description='Fixed tread depth in `unit` (overrides the riser/tread split).')] = None,
    width: Annotated[float | None, Field(description='Flight width in `unit`.')] = None,
    step_relation_min: Annotated[float | None, Field(description='Minimum 2R+G in `unit`; null = 550 mm equivalent.')] = None,
    step_relation_max: Annotated[float | None, Field(description='Maximum 2R+G in `unit`; null = 700 mm equivalent.')] = None,
    max_pitch_degrees: Annotated[float | None, Field(description='Maximum pitch angle in degrees; null = 42.')] = None,
) -> dict:
    """Calculate a straight stair flight: number of risers, riser height, tread depth, run
    length, pitch and the 2R+G step relation, checked against limits. Defaults are residential
    rules of thumb (max riser 190 mm, min tread 250 mm, 2R+G 550-700 mm, pitch <= 42 deg), NOT a
    building code -- pass your code's limits. Headroom, handrails and landings are not checked.
    Pure calculation; draws nothing."""
    from domain import architecture

    design = architecture.design_stair(floor_to_floor, units.unit_code(unit), max_riser=max_riser, min_tread=min_tread,
                                 tread=tread, width=width, step_relation_min=step_relation_min,
                                 step_relation_max=step_relation_max, max_pitch_degrees=max_pitch_degrees)
    return {"status": "ok", **design}


@cad_tool(toolset="architecture", kind="write", title="Draw stair plan", operation="emit_plan")
def autocad_draw_stair_plan(
    floor_to_floor: Annotated[float, Field(description='Total rise in `unit`; must be positive.')],
    unit: Annotated[str, Field(description="'m', 'mm', 'ft' or 'in'.")] = "mm",
    origin: Annotated[list[float] | None, Field(description='Stair origin [x, y]; null = (0, 0).')] = None,
    direction_degrees: Annotated[float, Field(description='Climb direction in degrees: 0, 90, 180 or 270.')] = 90.0,
    width: Annotated[float | None, Field(description='Flight width in `unit`.')] = None,
    max_riser: Annotated[float | None, Field(description='Maximum riser height in `unit`; null = 190 mm equivalent.')] = None,
    min_tread: Annotated[float | None, Field(description='Minimum tread depth in `unit`; null = 250 mm equivalent.')] = None,
    tread: Annotated[float | None, Field(description='Fixed tread depth in `unit` (overrides the riser/tread split).')] = None,
    text_height: Annotated[float | None, Field(description='Annotation text height in `unit`; null = the standard for these units.')] = None,
    dry_run: Annotated[bool, Field(description='Plan and report without drawing.')] = False,
) -> dict:
    """Design a straight flight (same rules and defaults as autocad_design_stair) and draw it in
    plan: outline, tread nosings, walking line with arrow and an "UP nR" note, starting at origin
    and climbing towards direction_degrees (0, 90, 180 or 270)."""
    from domain import architecture

    unit_code = units.unit_code(unit)
    design = architecture.design_stair(floor_to_floor, unit_code, max_riser=max_riser, min_tread=min_tread, tread=tread,
                                 width=width)
    point = _origin(origin)

    def build(code):
        return architecture.plan_stair(design, unit_code, code, origin=point, direction_degrees=direction_degrees,
                                 text_height=text_height)

    build(unit_code)
    outcome = backend().emit_plan(build, dry_run=dry_run)
    return _plan_result("stair_plan", outcome, dry_run, extra={"design": design})


@cad_tool(toolset="architecture", kind="write", title="Sheet border and title block", operation="emit_plan")
def autocad_draw_sheet(
    paper: Annotated[str, Field(description='Paper size: A0-A4, ANSI_A-ANSI_E or ARCH_A-ARCH_E.')] = "A3",
    scale: Annotated[float, Field(description='Plot scale denominator (1:scale; 100 = 1:100).')] = 100.0,
    orientation: Annotated[str, Field(description="'landscape' or 'portrait'.")] = "landscape",
    origin: Annotated[list[float] | None, Field(description='Sheet origin [x, y] in model space, in drawing units; null = (0, 0).')] = None,
    fields: Annotated[dict[str, str] | None, Field(description='Title block fields {project, title, drawing_number, scale, date, drawn_by, checked_by, sheet, revision}.')] = None,
    dry_run: Annotated[bool, Field(description='Plan and report without drawing.')] = False,
) -> dict:
    """Draw a sheet border, drawing frame and title block in model space at plot scale 1:scale
    (paper: A0-A4, ANSI_A-ANSI_E, ARCH_A-ARCH_E). fields fills the title block: project, title,
    drawing_number, scale (defaults to "1:scale"), date, drawn_by, checked_by, sheet, revision.
    Text sizes are paper sizes times the scale. Returns the usable drawing area."""
    from domain import architecture

    point = _origin(origin)

    def build(code):
        return architecture.plan_sheet(paper, scale, code, orientation=orientation, origin=point, fields=fields)

    build(1)
    outcome = backend().emit_plan(build, dry_run=dry_run)
    meta = outcome[0][0].meta
    return _plan_result("sheet", outcome, dry_run, extra={k: meta[k] for k in ("paper", "orientation", "paper_mm",
                                                                                "scale", "sheet_size_drawing_units",
                                                                                "drawing_area", "fields")})


# ======= civil / survey =======


@cad_tool(toolset="civil", kind="read", title="Alignment station and offset", operation="civil_alignment_station")
def autocad_civil_alignment_station(
    alignment: Handle,
    points: Points,
    start_station: Annotated[float, Field(description="Chainage at the centreline's first vertex (e.g. 0.0; 1000.0 when the design starts at CH 10+00).")] = 0.0,
) -> dict:
    """Station (chainage) and offset of one or more query points against a centreline drawn as a
    LINE or polyline (the alignment, given by handle). Stations run along the centreline in
    drawing units from its first vertex; start_station shifts the chainage (e.g. 1000.0 when the
    first station is CH 10+00). Offset is the perpendicular plan distance, positive to the right
    of the direction of increasing station, negative to the left. Each result carries station,
    offset, the closest point on the centreline (with its own z), the plan distance and the
    z difference. Arc bulges in a lightweight polyline are treated as straight chords and
    reported in notices. Read-only."""
    return backend().civil_alignment_station(alignment=alignment, points=points, start_station=start_station)


@cad_tool(toolset="civil", kind="read", title="Point at station and offset", operation="civil_station_point")
def autocad_civil_station_point(
    alignment: Handle,
    stations: Annotated[list[float], Field(description='Chainages along the centreline, in drawing units.')],
    offset: Annotated[float, Field(description='Perpendicular offset in drawing units; positive is right of the direction of increasing station.')] = 0.0,
    start_station: Annotated[float, Field(description="Chainage at the centreline's first vertex (e.g. 0.0; 1000.0 when the design starts at CH 10+00).")] = 0.0,
) -> dict:
    """The coordinates at one or more stations on a centreline (LINE or polyline by handle),
    at one perpendicular offset (positive to the right of the direction of increasing station).
    Each result carries the point [x, y, z], the tangent angle in degrees (AutoCAD convention:
    0 = east, counterclockwise) and whether the station had to be clamped to the centreline
    (a station before the start or past the end is clamped, never extrapolated). Useful for
    setting out: pass the design stations, get the coordinates to stake. Read-only."""
    return backend().civil_station_point(alignment=alignment, stations=stations, offset=offset,
                                         start_station=start_station)


@cad_tool(toolset="civil", kind="read", title="Ground profile from spot levels", operation="civil_ground_profile")
def autocad_civil_ground_profile(
    alignment: Handle,
    interval: Annotated[float, Field(description='Station spacing in drawing units (required; the tool has no default spacing).')],
    layer: Annotated[str | None, Field(description='Layer holding the spot-level POINT entities; null reads every layer.')] = None,
    offset: Annotated[float, Field(description='Perpendicular offset in drawing units; positive is right of increasing station.')] = 0.0,
    method: Annotated[str, Field(description="'idw' (inverse-distance weighting) or 'nearest' (closest level only).")] = "idw",
    neighbours: Annotated[int, Field(description='How many of the closest spot levels IDW uses (1 to 64).')] = 8,
    start_station: Annotated[float, Field(description="Chainage at the centreline's first vertex (e.g. 0.0; 1000.0 when the design starts at CH 10+00).")] = 0.0,
    max_entities: Annotated[int, Field(description='Read at most this many POINT entities (truncation is reported).')] = 20000,
) -> dict:
    """Ground levels sampled at a station interval along a centreline, from POINT entities that
    carry a Z (spot levels) on `layer` (all layers when None). interval is in drawing units and
    required -- the tool has no built-in spacing. method is 'idw' (inverse-distance weighting of
    the `neighbours` closest levels, power 2) or 'nearest'; exact hits on a point return that
    point's z. Rows are capped at 500 (rows_truncated says so); the end station is included as
    the last row. Reports the spot-level count and extents so you can judge coverage; the levels
    come from the drawing, not from a Civil 3D surface. Read-only."""
    return backend().civil_ground_profile(alignment=alignment, interval=interval, layer=layer, offset=offset,
                                          method=method, neighbours=neighbours, start_station=start_station,
                                          max_entities=max_entities)


@cad_tool(toolset="civil", kind="read", title="Cut and fill volumes", operation="civil_surface_volumes")
def autocad_civil_surface_volumes(
    existing_layer: Annotated[str, Field(description='Layer holding existing-ground POINT spot levels (their Z is the level).')],
    design_layer: Annotated[str, Field(description='Layer holding design-ground POINT spot levels.')],
    cell_size: Annotated[float, Field(description='Grid cell size in drawing units; must be positive.')],
    method: Annotated[str, Field(description="'idw' (inverse-distance weighting) or 'nearest'.")] = "idw",
    neighbours: Annotated[int, Field(description='How many of the closest spot levels IDW uses.')] = 8,
    max_entities: Annotated[int, Field(description='Read at most this many POINT entities per layer.')] = 20000,
) -> dict:
    """Cut and fill between two spot-level surfaces: existing ground from the Z of POINT entities
    on existing_layer, design/finished ground from the Z of POINT entities on design_layer.
    A square grid of cell_size (drawing units) covers the overlap of the two surfaces; every node
    is sampled from its surface (method 'idw' over `neighbours` levels, or 'nearest'). Each cell
    contributes cell_size squared x the mean (design - existing) of its corners: fill where the
    design surface is above, cut where below. Reports cut_volume, fill_volume, net_volume
    (positive = surplus fill), the grid used, and extrapolated_nodes -- nodes outside the spot
    levels' convex hull where the value is interpolated beyond the data. A drafting aid from the
    levels in the drawing, not a survey report. Read-only."""
    return backend().civil_surface_volumes(existing_layer=existing_layer, design_layer=design_layer,
                                           cell_size=cell_size, method=method, neighbours=neighbours,
                                           max_entities=max_entities)


@cad_tool(toolset="civil", kind="read", title="Pipe clearance check", operation="civil_pipe_clearance")
def autocad_civil_pipe_clearance(
    first: Handle,
    second: Handle,
    first_diameter: Annotated[float | None, Field(description='First pipe diameter in drawing units; give both diameters or neither.')] = None,
    second_diameter: Annotated[float | None, Field(description='Second pipe diameter in drawing units; give both diameters or neither.')] = None,
) -> dict:
    """Closest 3D approach between two pipe alignments drawn as LINE or polyline axes (handles),
    plus every place the two cross in plan with the vertical gap between them there. Give both
    diameters (drawing units) to also get surface_clearance = axis distance minus the two radii;
    give neither for axis-to-axis only. A clash hint from the geometry drawn, not a code check.
    Read-only."""
    return backend().civil_pipe_clearance(first=first, second=second, first_diameter=first_diameter,
                                          second_diameter=second_diameter)


@cad_tool(toolset="civil", kind="write", title="Place survey points", operation="civil_place_points")
def autocad_civil_place_points(
    points: Points,
    layer: LayerName = "C-POINT",
    label: Annotated[bool, Field(description='Add one numbered TEXT label per point.')] = True,
    text_height: Annotated[float | None, Field(description="Label text height in drawing units; null = the standard for the drawing's units.")] = None,
    start_number: Annotated[int, Field(description='First point number; labels count up from it.')] = 1,
) -> dict:
    """Place numbered point markers (POINT entities) at the given [x, y] or [x, y, z] coordinates,
    optionally with a label per point: the number, plus ' Z=<level>' when the z is not 0 (one TEXT
    entity). Numbers run from start_number upwards. text_height defaults to the standard text
    height for the drawing's units; layer defaults to 'C-POINT' and is created if missing. The
    markers adopt the drawing's current point display style (PDMODE), which this tool does not
    change. Up to 2000 points per call. Writes to the drawing and verifies every created entity
    by reading it back."""
    return backend().civil_place_points(points=points, layer=layer, label=label, text_height=text_height,
                                        start_number=start_number)


# ======= analysis =======


@cad_tool(toolset="analysis", kind="read", title="Check drawing", operation="snapshot_entities")
def autocad_check_drawing(
    rules: Annotated[list[str] | None, Field(description='Rule names to run (zero_length, degenerate_polyline, tiny_circle, duplicate, empty_text, on_layer_0, unclosed_wall_outline, text_height_variety, layer_name); null = all.')] = None,
    layer_pattern: Annotated[str | None, Field(description="Regex that layer names must match (e.g. '^[A-Z]-[A-Z0-9-]+$'); null skips the layer-name rule.")] = None,
    max_entities: Annotated[int, Field(description='Read at most this many entities (truncation is reported).')] = 20000,
    max_issues: Annotated[int, Field(description='Cap on findings returned (default 200).')] = 200,
) -> dict:
    """Read-only drafting checks on model space: zero_length, degenerate_polyline, tiny_circle,
    duplicate, empty_text, on_layer_0, unclosed_wall_outline, text_height_variety, and layer_name
    (when layer_pattern, a regex such as '^[A-Z]-[A-Z0-9-]+$', is given). Returns findings with
    handles and severities; changes nothing. Hygiene checks, not code compliance."""
    import re

    from domain import analysis

    if rules is not None and (not isinstance(rules, list) or not set(rules) <= set(analysis.RULES)):
        raise CadError(f"rules must be a list drawn from {sorted(analysis.RULES)}", code="E_INVALID_INPUT")
    if layer_pattern is not None:
        try:
            re.compile(layer_pattern)
        except re.error as exc:
            raise CadError(f"layer_pattern is not a valid regex: {exc}", code="E_INVALID_INPUT") from exc
    max_issues = validate_limit(max_issues, default=200, maximum=5000, label="max_issues")
    snap = backend().snapshot_entities(max_entities=max_entities)
    result = analysis.check(snap["entities"], rules=rules, layer_pattern=layer_pattern, max_issues=max_issues)
    return {"status": "ok", "drawing_identity": snap["drawing_identity"], "scan_truncated": snap["truncated"],
            **result, "message": f"{result['issue_count']} finding(s) in {result['entity_count']} entities."}


@cad_tool(toolset="analysis", kind="read", title="Quantity takeoff", operation="snapshot_entities")
def autocad_quantity_takeoff(
    layers: Annotated[list[str] | None, Field(description='Layers to measure; null = every layer.')] = None,
    wall_height: Annotated[float | None, Field(description='Wall face height in drawing units; enables wall face area and volume from A-WALL* outlines.')] = None,
    max_entities: Annotated[int, Field(description='Read at most this many entities (truncation is reported).')] = 20000,
) -> dict:
    """Measure model-space geometry per layer: line/polyline/arc lengths, closed-shape counts,
    areas and perimeters, circle and hatch areas, block counts, and wall length (plus face area
    and volume when wall_height, in drawing units, is given) from A-WALL* outlines. Converted to
    metres when the drawing's units are known. A measurement aid, not a bill of quantities."""
    from domain import analysis

    snap = backend().snapshot_entities(max_entities=max_entities)
    if wall_height is not None:
        from utils import geometry

        wall_height = geometry.validate_positive(wall_height, "wall_height")
    result = analysis.takeoff(snap["entities"], snap["units"]["insunits"], layers=layers, wall_height=wall_height)
    return {"status": "ok", "drawing_identity": snap["drawing_identity"], "scan_truncated": snap["truncated"],
            **result, "message": f"Measured {result['totals'].get('entities', 0)} entities on {len(result['layers'])} layer(s)."}


@cad_tool(toolset="analysis", kind="external", title="Save check/takeoff report", operation="snapshot_entities")
def autocad_save_report(
    report: Annotated[str, Field(description="'qc' runs autocad_check_drawing; 'takeoff' runs autocad_quantity_takeoff.")],
    path: Annotated[str, Field(description='Destination file path (absolute).')],
    format: Annotated[str, Field(description="'json', 'csv' or 'md'.")] = "json",
    overwrite: Annotated[bool, Field(description='Allow replacing an existing file.')] = False,
    rules: Annotated[list[str] | None, Field(description='Passed to autocad_check_drawing; null = all rules.')] = None,
    layer_pattern: Annotated[str | None, Field(description='Passed to autocad_check_drawing as the layer-name regex.')] = None,
    layers: Annotated[list[str] | None, Field(description='Passed to autocad_quantity_takeoff; null = every layer.')] = None,
    wall_height: Annotated[float | None, Field(description='Passed to autocad_quantity_takeoff as the wall face height.')] = None,
) -> dict:
    """Run autocad_check_drawing (report="qc") or autocad_quantity_takeoff (report="takeoff") and
    write the result to path as json, csv or md. Never touches the drawing; reports the file's
    size and SHA-256 read back from disk."""
    from core.reports import write_report

    if report == "qc":
        result = autocad_check_drawing(rules=rules, layer_pattern=layer_pattern)
    elif report == "takeoff":
        result = autocad_quantity_takeoff(layers=layers, wall_height=wall_height)
    else:
        raise CadError('report must be "qc" or "takeoff"', code="E_INVALID_INPUT")
    try:
        evidence = write_report(report, result, path, format, overwrite=overwrite,
                                context={"drawing_identity": result["drawing_identity"],
                                         "backend": session.backend_name(), "server_version": __version__})
    except ValueError as exc:
        if isinstance(exc, CadError):
            raise
        raise CadError(str(exc), code="E_INVALID_INPUT") from exc
    return {"status": "ok", "report": report, "file": evidence, "drawing_identity": result["drawing_identity"],
            "saved": False, "verified": evidence["size_bytes"] > 0, "verification": "file_on_disk",
            "message": f"Wrote {report} report to {evidence['path']}."}


@cad_tool(toolset="analysis", kind="read", title="Compare two DXF files")
def autocad_compare_dxf(path_a: Annotated[str, Field(description='Path to the first .dxf file to compare (treated as the older revision).')], path_b: Annotated[str, Field(description='Path to the second .dxf file to compare (treated as the newer revision).')], max_items: Annotated[int, Field(description='Cap on reported changed/added/removed items.')] = 200) -> dict:
    """Compare two DXF files (e.g. two revisions): entities matched by handle, then by geometry;
    reports changed (with the fields that changed), added, removed, and same-geometry-new-handle.
    Reads files only; needs ezdxf (pip install -e ".[dxf]") on either backend."""
    from backends.dxf import snapshot_file
    from domain import analysis

    a, b = snapshot_file(path_a), snapshot_file(path_b)
    result = analysis.compare(a["entities"], b["entities"], max_items=validate_limit(max_items, default=200, maximum=5000))
    return {"status": "ok", "old": {k: a[k] for k in ("path", "total", "dxf_version", "insunits", "audit")},
            "new": {k: b[k] for k in ("path", "total", "dxf_version", "insunits", "audit")}, **result,
            "message": "Identical." if result["identical"] else f"{result['summary']}"}


@cad_tool(toolset="analysis", kind="read", title="Validate a DXF file")
def autocad_validate_dxf_file(path: Annotated[str, Field(description='Path to the .dxf file to parse and audit.')]) -> dict:
    """Parse a DXF file in recover mode and report version, units, entity counts by type, layer and
    block counts, and every error the auditor found or had to fix. Reads the file only; needs ezdxf."""
    from backends.dxf import validate_file

    return validate_file(path)


@cad_tool(toolset="output", kind="external", title="Render preview image", operation="render_preview")
def autocad_render_preview(path: Annotated[str, Field(description='Destination image path (.png, .pdf or .svg); headless backend only.')], overwrite: Annotated[bool, Field(description='Allow replacing an existing file.')] = False) -> dict:
    """Headless backend: render model space to a .png, .pdf or .svg file with ezdxf's drawing
    add-on (needs matplotlib: pip install -e ".[render]"). Returns the file's size and SHA-256.
    The live backend uses autocad_plot_pdf instead."""
    return backend().render_preview(path=path, overwrite=overwrite)


# ======= resources and prompts =======


@server.resource("autocad://capabilities", name="capabilities", mime_type="application/json",
                 description="Which tools exist, their side effects, and which backend implements each.")
def resource_capabilities() -> str:
    import json

    return json.dumps(registry.capability_map(), indent=1)


@server.resource("autocad://units", name="units", mime_type="application/json",
                 description="Units presets, AutoCAD INSUNITS codes and the drafting defaults per unit system.")
def resource_units() -> str:
    import json

    return json.dumps({
        "presets": {k: dict(v) for k, v in units.UNIT_PRESETS.items()},
        "default_preset": units.DEFAULT_PRESET,
        "insunits": {code: name for code, (name, _mm) in units.INSUNITS.items()},
        "drafting_defaults": {"imperial_inches": units.defaults_for(1), "metric_mm": units.defaults_for(4)},
        "note": "Drafting conventions, not building-code requirements.",
    }, indent=1)


@server.resource("autocad://layer-standard", name="layer-standard", mime_type="application/json",
                 description="Layer names and colors the generators use (AIA/ISO 13567-style names).")
def resource_layer_standard() -> str:
    import json

    from domain import architecture
    from utils.constants import ARCHITECTURAL_LAYERS

    return json.dumps({
        "architectural": ARCHITECTURAL_LAYERS,
        "structural": {name: {"color_index": c, "linetype": lt} for name, (c, lt) in architecture.LAYERS.items()},
        "sheet": ["G-ANNO-TTLB", "G-ANNO-TTLB-TEXT"],
        "stairs": ["A-FLOR-STRS", "A-ANNO-NOTE"],
        "paper_sizes_mm": architecture.PAPER_SIZES_MM,
    }, indent=1)


@server.prompt(name="residential_floor_plan", title="Residential floor plan workflow",
               description="Step-by-step: rooms -> dry run -> draw -> check -> save.")
def prompt_residential_floor_plan(description: Annotated[str, Field(description="What the floor plan is for, e.g. 'a 2-bedroom house'.")] = "a 2-bedroom house") -> str:
    return (
        f"Draft a floor plan for {description}.\n"
        "1. autocad_get_status; on the live backend autocad_launch_application if needed.\n"
        "2. autocad_create_new_drawing(pin=true) and, for metric work, autocad_set_drawing_units('metric_mm').\n"
        "3. Write the rooms as rectangles {name, x, y, width, depth} measured to wall centrelines in one unit.\n"
        "4. autocad_generate_floor_plan(..., dry_run=true): read the schedules, unreachable_rooms and counts.\n"
        "5. Repeat with dry_run=false; then autocad_check_drawing and autocad_quantity_takeoff.\n"
        "6. autocad_draw_sheet for a border/title block if a sheet is wanted; autocad_save_drawing(path).\n"
        "State clearly that the result is a drafting aid, not an approved design."
    )


@server.prompt(name="drawing_review", title="Review an existing drawing",
               description="Read-only review: summary, checks, quantities, optional report.")
def prompt_drawing_review(path: Annotated[str, Field(description='DXF to open read-only for the review; empty reviews the active drawing.')] = "") -> str:
    target = f"Open {path} read-only with autocad_open_drawing, then " if path else ""
    return (
        f"{target}review the active drawing without changing it:\n"
        "1. autocad_drawing_summary (units, extents, layers, counts).\n"
        "2. autocad_check_drawing; group findings by severity and explain each rule that fired.\n"
        "3. autocad_quantity_takeoff for lengths/areas per layer.\n"
        "4. Offer autocad_save_report(report='qc', format='md') as evidence.\n"
        "Never call a tool whose state shows it changes the drawing during a review."
    )


@server.prompt(name="sheet_and_plot", title="Sheet and PDF",
               description="Title block, then a verified PDF (live backend) or preview (headless).")
def prompt_sheet_and_plot(paper: Annotated[str, Field(description="Paper size for the sheet (default 'A3').")] = "A3", scale: Annotated[str, Field(description="Plot scale denominator as text, e.g. '100' meaning 1:100.")] = "100") -> str:
    return (
        f"1. autocad_draw_sheet(paper='{paper}', scale={scale}, fields={{project, title, drawn_by, date}}).\n"
        "2. Live backend: autocad_plot_pdf(path) and report paper_mm and the SHA-256 from the result.\n"
        "   Headless backend: autocad_render_preview(path='sheet.pdf').\n"
        "3. autocad_save_drawing to keep the DWG/DXF that produced the PDF."
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    server.run("stdio")


if __name__ == "__main__":
    main()
