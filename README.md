# AutoCAD MCP Server

A local stdio MCP server that lets AI assistants (Claude Code, OpenCode, Codex
CLI, Claude Desktop) draft, edit, inspect and check AutoCAD drawings. It drives
**AutoCAD 2021+ on Windows over COM** (`com` backend), or edits **DXF files
headlessly** with ezdxf (`dxf` backend).

Version **0.3.0**. This is a drafting aid for students and drafters: nothing it
produces is a structural design, a building-code check, or a professional bill
of quantities.

<!-- generated:start summary -->
**70 MCP tools** in 11 toolsets; **650 catalogued capabilities**: 62 verified live, 165 tested, 26 implemented, 397 planned. Status words mean exactly what `docs/capabilities.json` says: only a live AutoCAD test promotes a capability to `verified`.
<!-- generated:end summary -->

## Quick start

Prerequisite: Python 3.10+ (tested on 3.14) and Git. Live use also needs a full
AutoCAD 2021+ on Windows (not LT; LT has no COM).

```powershell
git clone <repo-url>
cd AutoCad-MCP
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dxf.txt   # optional: headless backend
python src\server.py                   # speaks MCP over stdio; normally started by your client
```

After `pip install -e .` the server also runs as `autocad-mcp`.

## Connect a client

Use absolute paths. Ask the client to call `autocad_get_status` to confirm.

**Claude Code**

```powershell
claude mcp add autocad --scope user -e AUTOCAD_MCP_BACKEND=com -- "C:\path\to\AutoCad-MCP\.venv\Scripts\python.exe" "C:\path\to\AutoCad-MCP\src\server.py"
```

**OpenCode**

```powershell
opencode mcp add autocad --env AUTOCAD_MCP_BACKEND=com -- "C:\path\to\AutoCad-MCP\.venv\Scripts\python.exe" "C:\path\to\AutoCad-MCP\src\server.py"
```

**Codex CLI** (`~/.codex/config.toml`)

```toml
[mcp_servers.autocad]
command = 'C:\path\to\AutoCad-MCP\.venv\Scripts\python.exe'
args = ['C:\path\to\AutoCad-MCP\src\server.py']
startup_timeout_sec = 30
tool_timeout_sec = 300
```

**Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json`)

```json
{ "mcpServers": { "autocad": {
    "command": "C:\\path\\to\\AutoCad-MCP\\.venv\\Scripts\\python.exe",
    "args": ["C:\\path\\to\\AutoCad-MCP\\src\\server.py"] } } }
```

## Backend selection

The backend comes from `AUTOCAD_MCP_BACKEND` once per process. There is never a
silent fallback between `com` and `dxf`: a live-drawing session cannot turn into
editing an in-memory DXF.

| Variable | Default | Effect |
|---|---|---|
| `AUTOCAD_MCP_BACKEND` | `com` | `com` (live AutoCAD) or `dxf` (headless ezdxf) |
| `AUTOCAD_MCP_UNITS` | `engineering` | units preset drawing tools apply; `preserve` = never change units |
| `AUTOCAD_MCP_COM_TIMEOUT` | `120` | seconds per live COM call |
| `AUTOCAD_MCP_TOOLSETS` | `all` | e.g. `core,drawing,query` to advertise fewer tools |
| `AUTOCAD_MCP_OUTPUT_DIR` | `Documents\AutoCAD MCP Output` | where relative output paths go |
| `AUTOCAD_MCP_ALLOWED_DIRS` | unset | confine every file path a tool accepts (`;`-separated) |

## Tools and strict schemas

Every tool returns JSON. Failures return an error envelope (`code`, `message`,
`recoverable`, `recommended_action`, `details`); mutating tools add a `state`
block (`accepted`, `preflight_passed`, `executed`, `verified`, `saved`).
`verified` is true only after the result was read back; `saved` only after a
save tool wrote the file and its SHA-256 was read back.

**Argument rules for AI agents:**

1. Pass only arguments listed in the tool's input schema. Every parameter has a
   description there; descriptions state units, formats and defaults.
2. Coordinates are `[x, y]` or `[x, y, z]` in the drawing's own units
   (`autocad_get_status` / `autocad_drawing_summary` report them). Angles are
   degrees, counterclockwise.
3. Destructive tools default to `dry_run: true`: read the returned plan, then
   repeat the call with `dry_run: false`.
4. `saved: false` in a result means the drawing still needs
   `autocad_save_drawing`.

Typical flow: `autocad_get_status` -> `autocad_launch_application` (live only)
-> `autocad_create_new_drawing` / `autocad_open_drawing` ->
`autocad_pin_document` -> drawing tools -> `autocad_save_drawing`.

Tools are grouped in toolsets; `AUTOCAD_MCP_TOOLSETS` hides the ones a client
does not need.

<!-- generated:start tools -->
70 tools in 11 toolsets. Argument schemas are generated from typed signatures; every parameter carries a description. 

| Toolset | Tools | Purpose |
|---|---|---|
| `core` | 13 | status, launch, capabilities, document lifecycle, pinning, units |
| `drawing` | 7 | 2D primitives: lines, polylines, rectangles, circles, arcs, text, MTEXT |
| `layers` | 4 | layer creation, listing and properties |
| `editing` | 12 | move, rotate, copy, scale, mirror, offset, array, delete, properties, highlight |
| `query` | 6 | drawing summary, entity listing and detail, scan to SQLite, read-only SQL, text search |
| `annotation` | 2 | dimensions and hatches |
| `blocks` | 4 | block definitions, insertion and attributes |
| `architecture` | 7 | walls, floor plans, stairs, structural grids, sheets and title blocks |
| `analysis` | 5 | drawing checks, quantity takeoff, DXF comparison |
| `output` | 4 | DXF export, PDF plotting, layouts, previews, file evidence |
| `civil` | 6 | alignment stationing, ground profiles, cut/fill volumes, pipe clearance, COGO points |

### `core`

| Tool | Kind | Backends | Description |
|---|---|---|---|
| `autocad_activate_drawing` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Make the open drawing with this identity the active one. While a document pin is set this refuses unless pin=true, which moves the pin. |
| `autocad_close_drawing` | can remove or overwrite work | com, dxf | Close a drawing (default: the active one) without saving. Refuses when it has unsaved changes unless discard_changes=true. Closing the pinned drawing removes the pin. |
| `autocad_create_new_drawing` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Create a new, unsaved drawing (live: Documents.Add; headless: a new in-memory DXF). Never touches disk, so it cannot overwrite a file. template, if given, is a .dwt path (or a bare template name AutoCAD finds on its template path). If a document pin is set, this refuses unless pin=true, which moves the pin to the new drawing. |
| `autocad_create_test_drawing_with_line` | writes files or starts processes | com | Create a new drawing, draw one line from (0,0,0) to (100,100,0), save it as mcp_test_<timestamp>.dwg under output_dir (default: Documents/AutoCAD MCP Output), and verify the entity and file exist. Requires AutoCAD to already be connected; call autocad_get_status / autocad_launch_application first. |
| `autocad_get_capabilities` | read-only | com, dxf | Machine-readable description of this server: version, pinned backend, enabled toolsets, every registered tool with its side-effect kind and the backends that implement it, the configuration in force (units preset, COM timeout, allowed output folders) and COM worker statistics. Use it instead of guessing what a backend supports. |
| `autocad_get_status` | read-only | com, dxf | Report the backend this server is pinned to and, for the live backend, whether AutoCAD 2021+ is installed, running, reachable over COM and a supported release; plus a best-effort OpenCode session detection flag and the document pin. Never starts AutoCAD. |
| `autocad_launch_application` | writes files or starts processes | com | Launch AutoCAD if not already running, and wait until it answers COM calls. Does nothing destructive if AutoCAD is already running; just verifies it. Live backend only. |
| `autocad_list_drawings` | read-only | com, dxf | List open drawings with identity, path, unsaved-changes flag, read-only flag and which one is active. Use an identity from here with autocad_activate_drawing / autocad_close_drawing. |
| `autocad_open_drawing` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Open a .dwg/.dxf/.dwt/.dws file (read-only by default -- pass read_only=false to edit it) and make it active; an already-open file is just activated. While a document pin is set this refuses unless pin=true, which moves the pin to the opened drawing. |
| `autocad_pin_document` | session state only | com, dxf | Pin this session to the active drawing: until autocad_unpin_document, every tool refuses (E_DOCUMENT_CHANGED, nothing changed) if a different drawing becomes active -- e.g. the user switches drawing tabs mid-job. identity, if given, must equal the active drawing's identity (as reported in drawing_identity); otherwise the active drawing is pinned. Saving an unsaved drawing changes its identity; pin again after the first save. |
| `autocad_save_drawing` | can remove or overwrite work | com, dxf | Save the active drawing. path=None saves to its own file (it must have been saved before and not be read-only). With path: save as that .dwg (or .dxf with format="dxf"); an existing different file is only replaced with overwrite=true. Save-as re-points the open drawing at the new file (a pin follows it); use autocad_export_dxf to write a copy instead. version: R2000, R2004, R2007, R2010, R2013, R2018. Reports the file's size and SHA-256 read back from disk. |
| `autocad_set_drawing_units` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Apply a units preset to the active drawing and keep it for this session (drawing tools then stop re-applying the AUTOCAD_MCP_UNITS default): engineering (feet + decimal inches, INSUNITS inches), architectural (feet + fractional inches), metric_mm (INSUNITS mm), metric_m (INSUNITS m), or preserve (stop changing units at all). Reports every variable changed. |
| `autocad_unpin_document` | session state only | com, dxf | Remove the document pin set by autocad_pin_document. Tools then act on whichever drawing is active, as before pinning. |

### `drawing`

| Tool | Kind | Backends | Description |
|---|---|---|---|
| `autocad_draw_arc` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Draw a counterclockwise arc around center from start_angle_degrees to end_angle_degrees (degrees from +X). Reports the angles and arc length read back. |
| `autocad_draw_circle` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Draw a circle at center ([x, y] or [x, y, z]) with a positive radius. |
| `autocad_draw_line` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Draw a line between two validated points in the active drawing's ModelSpace. Points are [x, y] or [x, y, z]; z defaults to 0. |
| `autocad_draw_mtext` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Add multiline text (top-left at insertion_point). width 0 = no wrapping; \P in text starts a new paragraph. |
| `autocad_draw_polyline` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Draw a polyline through an ordered list of >=2 points ([x, y] or [x, y, z], z defaults to 0), optionally closed, as an AcDb3dPolyline. |
| `autocad_draw_rectangle` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Draw an axis-aligned rectangle (as a closed polyline). Give exactly one of: corner1 and corner2 (opposite corners, same z-plane), or base_point with positive width and height. |
| `autocad_draw_text` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Add single-line text at insertion_point with a positive height and an optional rotation in degrees (counterclockwise, viewed from +Z). |

### `layers`

| Tool | Kind | Backends | Description |
|---|---|---|---|
| `autocad_create_layer` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Create a layer if it doesn't exist. color_index (0-255) and linetype, when given, update that property on an existing layer; every other layer property (locked, frozen, on/off, ...) is left untouched. |
| `autocad_ensure_layer` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Same as autocad_create_layer, except a name matching the architectural layer standard (A-WALL, A-WALL-EXT, A-WALL-INT, A-DOOR, A-GLAZ, A-ANNO, A-TEXT, A-DIM, ...) falls back to that standard's color_index/linetype when not given explicitly. An explicit color_index/linetype always overrides it. |
| `autocad_list_layers` | read-only | com, dxf | List every layer with on/frozen/locked state, color, linetype, lineweight, plottable flag, and which one is current. |
| `autocad_set_layer_properties` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Change only the given properties of an existing layer and read them back. lineweight is in hundredths of a millimetre (25 = 0.25 mm, -3 = Default). A linetype that isn't loaded is loaded from acad.lin / acadiso.lin. The current layer cannot be frozen. |

### `editing`

| Tool | Kind | Backends | Description |
|---|---|---|---|
| `autocad_array_rectangular` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Copy the entity into a rows x columns grid (row_spacing along Y, column_spacing along X; the original is the first cell). Returns the rows*columns-1 new handles. |
| `autocad_copy_entity` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Copy the entity with this handle, offsetting the copy by a validated [dx, dy, dz] vector. Returns the new entity's handle. |
| `autocad_delete_entities` | can remove or overwrite work | com, dxf | Delete entities by handle. dry_run=true (the default) only lists what would be deleted and changes nothing; call again with dry_run=false to delete. Verifies each deleted handle no longer resolves. Ctrl+Z in AutoCAD can undo it. |
| `autocad_highlight_entity` | changes the drawing or AutoCAD's state, never removes work | com | Highlight an entity. method="temporary" uses AutoCAD's native Highlight() flag (a visual-only state, not saved to the DWG, that never touches the entity's Color property) -- pass clear=True to turn it back off. method="persistent" sets entity.Color (0-255) and does not revert. |
| `autocad_highlight_text_matches` | changes the drawing or AutoCAD's state, never removes work | com | Find TEXT/MTEXT entities matching pattern (literal substring, or a regex if use_regex=True) and highlight them the same way as autocad_highlight_entity. Never modifies the matched entities' text. Every match is highlighted; the returned list holds at most `limit` of them. |
| `autocad_mirror_entity` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Mirror the entity across the line axis_start-axis_end. Returns the mirrored copy's handle; keep_original=false deletes the source afterwards. |
| `autocad_move_entity` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Move the entity with this handle by a validated [dx, dy, dz] vector. |
| `autocad_offset_entity` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Offset a curve (line, arc, circle, polyline, ellipse, spline) by distance; the sign picks the side. Returns the new handles. |
| `autocad_query_and_highlight` | changes the drawing or AutoCAD's state, never removes work | com | Run a read-only query (same rules as autocad_execute_query) whose result set includes a 'handle' column, then highlight every matching entity the same way as autocad_highlight_entity. Stale handles (entity deleted since the last scan) are reported in not_found, not raised. |
| `autocad_rotate_entity` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Rotate the entity with this handle about base_point by angle_degrees (counterclockwise-positive, viewed from +Z -- AutoCAD's own convention). |
| `autocad_scale_entity` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Scale the entity uniformly about base_point by a positive factor; verifies the extents changed by that factor. |
| `autocad_set_entity_properties` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Set layer / color (ACI 0-256: 0 ByBlock, 256 ByLayer) / linetype / lineweight (hundredths of mm, -1 ByLayer) on one or more entities and read them back. A missing layer is created. |

### `query`

| Tool | Kind | Backends | Description |
|---|---|---|---|
| `autocad_count_text_patterns` | read-only | com, dxf | Count TEXT/MTEXT entities in the active drawing whose text matches pattern: a literal substring by default, or a regex if use_regex=True. match_count is the full count; at most `limit` matches are listed. |
| `autocad_drawing_summary` | read-only | com, dxf | Compact overview of the active drawing: identity, saved/unsaved state, units (INSUNITS, LUNITS, imperial/metric), extents, entity counts by type and by layer, layers, block definitions and layouts. Reads at most max_entities model-space entities (truncated says if more exist). Start here before editing an unfamiliar drawing. |
| `autocad_execute_query` | read-only | com, dxf | Run one read-only SELECT (optionally with a WITH clause) against the scanned-entities database. Writes, DDL, PRAGMA, and multi-statement input are rejected; use params for a parameterized query (never string- format user values into the query text). At most `limit` rows are returned; `truncated` says whether more matched. |
| `autocad_get_entity` | read-only | com, dxf | Full detail of one entity: type, layer, color, linetype, lineweight, geometry (points, center/radius, angles in degrees, text, block name and attributes, hatch pattern and area, dimension measurement), length/area where AutoCAD reports them, and bounding box. |
| `autocad_list_entities` | read-only | com, dxf | Page through model-space entities as {handle, type, layer}, optionally filtered by DXF type names (LINE, LWPOLYLINE, POLYLINE3D, CIRCLE, ARC, TEXT, MTEXT, INSERT, HATCH, DIMENSION, ...), layer names, and a bbox window [[xmin, ymin], [xmax, ymax]] the entity must lie inside. Use offset/next_offset to page; total counts every match. |
| `autocad_scan_all_entities` | read-only | com, dxf | Scan top-level ModelSpace entities (lines, circles, polylines, text/mtext -- not block references or PaperSpace) and replace this drawing's snapshot in the local SQLite database (other drawings' records are untouched; rescanning is idempotent). Never modifies the drawing. |

### `annotation`

| Tool | Kind | Backends | Description |
|---|---|---|---|
| `autocad_add_dimension` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Add a dimension between two points using the current dimension style. kind="aligned" measures along the points; kind="linear" measures along rotation_degrees (0 horizontal, 90 vertical). The dimension line passes through dimension_line_point. Verifies the measurement AutoCAD reports equals the geometry. |
| `autocad_add_hatch` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Hatch one closed area: give boundary_handles (closed curves already drawn) or boundary_points (a polygon; a boundary polyline is drawn and kept unless keep_boundary=false). pattern is a predefined pattern name (ANSI31, SOLID, AR-CONC, ...). Reports the hatched area and verifies the pattern read back. |

### `blocks`

| Tool | Kind | Backends | Description |
|---|---|---|---|
| `autocad_get_block_attributes` | read-only | com, dxf | List the attributes (tag, value, handle) of a block reference. |
| `autocad_insert_block` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Insert a block already defined in the drawing, optionally filling attributes {TAG: value}. Unknown tags are rejected before anything is inserted; values are read back. |
| `autocad_list_blocks` | read-only | com, dxf | List block definitions (not layouts) with entity count, attribute tags, and xref status. |
| `autocad_set_block_attributes` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Update attribute values {TAG: text} on a block reference and read them back. Unknown tags are rejected before any change. |

### `architecture`

| Tool | Kind | Backends | Description |
|---|---|---|---|
| `autocad_design_stair` | read-only | com, dxf | Calculate a straight stair flight: number of risers, riser height, tread depth, run length, pitch and the 2R+G step relation, checked against limits. Defaults are residential rules of thumb (max riser 190 mm, min tread 250 mm, 2R+G 550-700 mm, pitch <= 42 deg), NOT a building code -- pass your code's limits. Headroom, handrails and landings are not checked. Pure calculation; draws nothing. |
| `autocad_draw_sheet` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Draw a sheet border, drawing frame and title block in model space at plot scale 1:scale (paper: A0-A4, ANSI_A-ANSI_E, ARCH_A-ARCH_E). fields fills the title block: project, title, drawing_number, scale (defaults to "1:scale"), date, drawn_by, checked_by, sheet, revision. Text sizes are paper sizes times the scale. Returns the usable drawing area. |
| `autocad_draw_stair_plan` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Design a straight flight (same rules and defaults as autocad_design_stair) and draw it in plan: outline, tread nosings, walking line with arrow and an "UP nR" note, starting at origin and climbing towards direction_degrees (0, 90, 180 or 270). |
| `autocad_draw_structural_grid` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Draw a column grid: x_spacings are bay widths left to right (lines numbered 1, 2, 3...), y_spacings bay depths bottom to top (lettered A, B, C...; I and O skipped unless skip_letters=false), in `unit`. Lines (layer S-GRID, CENTER linetype) end in labelled bubbles; column_size [width, depth] adds a filled column mark at every intersection; bay and overall dimensions are added. Drafting of a chosen grid, not structural design. |
| `autocad_draw_wall` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Draw a wall as a closed double-line outline (4-point polyline) centered on start_point-end_point, offset by thickness/2 on each side. Coordinates and thickness are in the drawing's units. thickness defaults to the standard exterior wall for those units (9 in in inch drawings -- the V0.2.x default -- or 230 mm in millimetre drawings). Creates the layer via autocad_ensure_layer if it doesn't already exist. |
| `autocad_generate_2d_floor_plan` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Generate a complete residential floor plan in one call: 9" exterior walls, 4.5" interior partitions splitting the footprint into a fixed 2x3 room grid (Living Room, Kitchen, Bath, 2 Bedrooms by default -- override with rooms_config), a 36" main entry door and a 30" interior door per room, a 48" window per room touching an exterior wall, and an MTEXT room label per room. width_ft/length_ft is the footprint in feet; drawing happens in inches, matching the Engineering units preset applied by default (in a millimetre drawing the same plan is drawn converted to mm). units ("INCHES" or "FEET") adds room bounds in feet when "FEET". dry_run=true returns the planned entities without drawing anything. |
| `autocad_generate_floor_plan` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Draw a residential floor plan from explicit rooms. rooms: [{name, x, y, width, depth}] in `unit` (ft, in, m, mm), measured to wall centrelines; rooms must not overlap and may form any rectilinear footprint. Exterior walls follow the outline, interior walls the shared edges (defaults 9"/4.5" or 230/115 mm, override with exterior_wall/interior_wall in `unit`). Doors: omit to connect every room to the entry room (entry_room, default the first) through shared walls, or give [{between: [roomA, roomB], width?, position? 0-1}]; a main door goes on the entry room's outside wall. windows="auto" puts one per room on its longest outside wall, "none" skips them. Labels show the clear (net) area. Returns room, door and window schedules. dry_run=true shows the plan without drawing. Drafting aid, not a design check. |

### `analysis`

| Tool | Kind | Backends | Description |
|---|---|---|---|
| `autocad_check_drawing` | read-only | com, dxf | Read-only drafting checks on model space: zero_length, degenerate_polyline, tiny_circle, duplicate, empty_text, on_layer_0, unclosed_wall_outline, text_height_variety, and layer_name (when layer_pattern, a regex such as '^[A-Z]-[A-Z0-9-]+$', is given). Returns findings with handles and severities; changes nothing. Hygiene checks, not code compliance. |
| `autocad_compare_dxf` | read-only | com, dxf | Compare two DXF files (e.g. two revisions): entities matched by handle, then by geometry; reports changed (with the fields that changed), added, removed, and same-geometry-new-handle. Reads files only; needs ezdxf (pip install -e ".[dxf]") on either backend. |
| `autocad_quantity_takeoff` | read-only | com, dxf | Measure model-space geometry per layer: line/polyline/arc lengths, closed-shape counts, areas and perimeters, circle and hatch areas, block counts, and wall length (plus face area and volume when wall_height, in drawing units, is given) from A-WALL* outlines. Converted to metres when the drawing's units are known. A measurement aid, not a bill of quantities. |
| `autocad_save_report` | writes files or starts processes | com, dxf | Run autocad_check_drawing (report="qc") or autocad_quantity_takeoff (report="takeoff") and write the result to path as json, csv or md. Never touches the drawing; reports the file's size and SHA-256 read back from disk. |
| `autocad_validate_dxf_file` | read-only | com, dxf | Parse a DXF file in recover mode and report version, units, entity counts by type, layer and block counts, and every error the auditor found or had to fix. Reads the file only; needs ezdxf. |

### `output`

| Tool | Kind | Backends | Description |
|---|---|---|---|
| `autocad_export_dxf` | writes files or starts processes | com, dxf | Write a DXF copy of the active drawing to path (.dxf) without renaming or re-pointing the open drawing (unlike save-as). Existing files are replaced only with overwrite=true, and only after the new file was written. Reports size and SHA-256 read back from disk. |
| `autocad_list_layouts` | read-only | com, dxf | List layouts (Model and paper-space sheets) with plot device, paper, plot style and which one is current. |
| `autocad_plot_pdf` | writes files or starts processes | com | Plot to a PDF with AutoCAD's 'DWG To PDF.pc3'. layout=None plots model space to its extents, fitted to the paper; a layout name plots that sheet at 1:1. paper is a canonical media name or a unique part of one (e.g. 'ISO_full_bleed_A3'); plot_style e.g. 'monochrome.ctb'. The layout's plot settings and BACKGROUNDPLOT are restored afterwards. Verifies the PDF on disk and reports its paper size in mm. |
| `autocad_render_preview` | writes files or starts processes | dxf | Headless backend: render model space to a .png, .pdf or .svg file with ezdxf's drawing add-on (needs matplotlib: pip install -e ".[render]"). Returns the file's size and SHA-256. The live backend uses autocad_plot_pdf instead. |

### `civil`

| Tool | Kind | Backends | Description |
|---|---|---|---|
| `autocad_civil_alignment_station` | read-only | com, dxf | Station (chainage) and offset of one or more query points against a centreline drawn as a LINE or polyline (the alignment, given by handle). Stations run along the centreline in drawing units from its first vertex; start_station shifts the chainage (e.g. 1000.0 when the first station is CH 10+00). Offset is the perpendicular plan distance, positive to the right of the direction of increasing station, negative to the left. Each result carries station, offset, the closest point on the centreline (with its own z), the plan distance and the z difference. Arc bulges in a lightweight polyline are treated as straight chords and reported in notices. Read-only. |
| `autocad_civil_ground_profile` | read-only | com, dxf | Ground levels sampled at a station interval along a centreline, from POINT entities that carry a Z (spot levels) on `layer` (all layers when None). interval is in drawing units and required -- the tool has no built-in spacing. method is 'idw' (inverse-distance weighting of the `neighbours` closest levels, power 2) or 'nearest'; exact hits on a point return that point's z. Rows are capped at 500 (rows_truncated says so); the end station is included as the last row. Reports the spot-level count and extents so you can judge coverage; the levels come from the drawing, not from a Civil 3D surface. Read-only. |
| `autocad_civil_pipe_clearance` | read-only | com, dxf | Closest 3D approach between two pipe alignments drawn as LINE or polyline axes (handles), plus every place the two cross in plan with the vertical gap between them there. Give both diameters (drawing units) to also get surface_clearance = axis distance minus the two radii; give neither for axis-to-axis only. A clash hint from the geometry drawn, not a code check. Read-only. |
| `autocad_civil_place_points` | changes the drawing or AutoCAD's state, never removes work | com, dxf | Place numbered point markers (POINT entities) at the given [x, y] or [x, y, z] coordinates, optionally with a label per point: the number, plus ' Z=<level>' when the z is not 0 (one TEXT entity). Numbers run from start_number upwards. text_height defaults to the standard text height for the drawing's units; layer defaults to 'C-POINT' and is created if missing. The markers adopt the drawing's current point display style (PDMODE), which this tool does not change. Up to 2000 points per call. Writes to the drawing and verifies every created entity by reading it back. |
| `autocad_civil_station_point` | read-only | com, dxf | The coordinates at one or more stations on a centreline (LINE or polyline by handle), at one perpendicular offset (positive to the right of the direction of increasing station). Each result carries the point [x, y, z], the tangent angle in degrees (AutoCAD convention: 0 = east, counterclockwise) and whether the station had to be clamped to the centreline (a station before the start or past the end is clamped, never extrapolated). Useful for setting out: pass the design stations, get the coordinates to stake. Read-only. |
| `autocad_civil_surface_volumes` | read-only | com, dxf | Cut and fill between two spot-level surfaces: existing ground from the Z of POINT entities on existing_layer, design/finished ground from the Z of POINT entities on design_layer. A square grid of cell_size (drawing units) covers the overlap of the two surfaces; every node is sampled from its surface (method 'idw' over `neighbours` levels, or 'nearest'). Each cell contributes cell_size squared x the mean (design - existing) of its corners: fill where the design surface is above, cut where below. Reports cut_volume, fill_volume, net_volume (positive = surplus fill), the grid used, and extrapolated_nodes -- nodes outside the spot levels' convex hull where the value is interpolated beyond the data. A drafting aid from the levels in the drawing, not a survey report. Read-only. |
<!-- generated:end tools -->

The machine-readable capability catalog (status evidence per capability, never
promoted without a test) is in [`docs/capabilities.json`](docs/capabilities.json).

## Architecture

```
MCP client --stdio--> src/server.py        (tools, resources, prompts, envelopes)
                          |
               src/core/          errors, session/pin, registry, catalog, paths,
               |                  evidence, reports, COM executor, SQLite cache
               src/backends/      base (contract), com (live), dxf (headless),
               |                  com_engine (COM plumbing), targets (plan emitters)
               src/domain/        pure logic: units, architecture, analysis, civil
               src/tools/         COM implementations used by ComBackend
```

Generators build a plan first, then draw it through one emitter on either
backend and verify the entity count.

One-way imports: `server -> tools -> backends -> core/domain/utils`. `domain`
and `core` never import pywin32 or ezdxf; `server`, `backends.dxf` and `domain`
import without pywin32 (test-enforced).

## Safety model

* Local stdio server; no network listener.
* No tool executes raw AutoCAD commands, AutoLISP, Python, shell or arbitrary
  SQL. `autocad_execute_query` runs one read-only SELECT against the scan
  cache, with two write guards; it cannot reach AutoCAD or the file system.
* One COM thread with a per-call timeout; a stuck call is abandoned, never
  allowed to hang the server.
* Document pinning: a tab switch cannot redirect a job to another drawing.
* Deletes default to dry runs; overwriting another file needs
  `overwrite=true`; closing with unsaved changes needs `discard_changes=true`.
* Read-only tools never change units and never send keystrokes.
* File paths are validated; `AUTOCAD_MCP_ALLOWED_DIRS` confines them.
* The server acts with your user rights on whatever your AutoCAD has open: pin
  the drawing for a job.

## Limitations

* Live-verified on AutoCAD 2024 only, and only what the live tests assert
  (see `docs/capabilities.json`, status `verified`). Other releases have not
  been run.
* No undo-group or transaction tool yet; use AutoCAD's Undo.
* Floor plans draw doors and windows over walls, not cut into them.
* Scans, checks and takeoff read top-level model space only.
* Headless backend: DXF only, one drawing at a time; DWG, plotting, highlighting
  and launching are refused with the reason.
* Civil 3D, Map 3D, Plant 3D, Electrical and LT features are not implemented.

## Tests

```powershell
pip install pytest
python -m pytest tests -q          # live tests skip without AutoCAD
python -m pytest tests\test_integration_autocad.py -v   # needs a running AutoCAD
python scripts\build_capabilities.py --check            # generated files fresh
```

Test layers: unit (pure logic), fake-COM (what this code sends to AutoCAD),
headless DXF (real files re-read with ezdxf), golden regression, stdio
end-to-end, live AutoCAD. Fake-COM tests prove what this code sends; they prove
nothing about AutoCAD. Only a live test may promote a capability to `verified`.
Never skip or loosen a failing test to get a green run.

## Repository layout

| Path | Contents |
|---|---|
| `src/server.py` | MCP surface: tool functions, resources, prompts; `cad_tool` builds the error envelope and state block |
| `src/core/` | errors, session, registry, catalog, paths, evidence, reports, hosts, executor, `db.py` (scan cache) |
| `src/backends/` | `base.py` (operation contract), `com.py` (live), `com_engine.py` (COM plumbing), `dxf.py` (headless), `targets.py` (plan emitters) |
| `src/domain/` | pure logic: `units.py`, `architecture.py`, `analysis.py`, `civil.py` |
| `src/tools/` | COM implementations: `core.py`, `drawing.py`, `editing.py`, `annotation.py`, `output.py`, `civil.py` |
| `tests/` | unit, fake-COM (`fakes.py`), golden, headless, stdio e2e, live (`test_integration_autocad.py`) |
| `scripts/` | `build_capabilities.py` (generates `docs/capabilities.json` and this README's tables) |

## Contributing

For coding agents (Claude Code, Codex, OpenCode) and humans. These rules are
binding:

1. **No escape hatches.** No tool may execute raw AutoCAD commands, AutoLISP,
   Python, shell commands or arbitrary SQL writes.
2. **Backend pinning.** Never fall back from `com` to `dxf` (or back) silently.
3. **One COM thread.** Every COM call goes through `ComBackend._call` on the
   executor thread with a timeout. Never touch COM objects from another thread
   or cache them across calls.
4. **Document choke point.** Writes pass `for_write=True` (pin check, pending
   command cancel, units policy); reads pass `for_write=False` and must not
   change units or send keystrokes.
5. **Typed errors.** Raise `core.errors.CadError` subclasses with a code from
   `ERROR_CODES` and a `recommended_action`. Never return `{"ok": false}`,
   never swallow exceptions, never print to stdout (stdout is the MCP channel).
6. **Honest states.** `verified` only after a read-back; `saved` only after the
   file and its SHA-256 were read back.
7. **Bounded output.** Listing tools take `limit` (and `offset` where useful)
   and report `truncated` and totals.
8. **Files.** Use `core.paths.output_path` / `input_path`. Never overwrite
   without `overwrite=true`.
9. **Units.** No hard-coded inches or millimetres outside `domain.units`; no
   national code values as defaults (limits are parameters, labelled
   rule-of-thumb).
10. **Compatibility.** Keep every V0.2.x tool name and required argument.
    Behaviour changes go in the capability catalog and the commit message.
11. **Evidence.** Status words mean exactly `planned` (no code),
    `implemented` (code, no automated test), `tested` (automated tests:
    unit, mock_com, headless_dxf, stdio_e2e, golden_regression), `verified`
    (a live AutoCAD test asserts it, listed in `src/core/catalog/data.py`).
    Never promote without evidence. Fake-COM tests are never described as live.
12. **Live tests** use only scratch drawings they create and close. Never point
    tests or tools at a real project drawing. Do not launch AutoCAD without the
    owner's go-ahead.

Work on a branch; do not commit to `main` directly. Commit or push only when
the owner asks. Never commit real project drawings, client configs, `.venv`,
caches or output folders.

Adding a tool: pure logic in `src/domain/` with unit tests; operation name in
`Backend.OPERATIONS` plus the backend implementations (a backend that cannot do
it refuses with `E_UNSUPPORTED_BACKEND`, reason in `UNSUPPORTED_REASONS`);
register in `src/server.py` with `@cad_tool(...)`; typed parameters with
descriptions in the signature; tests (fake-COM, headless, expected-tools set,
live); catalog entry in `src/core/catalog/data.py` with the honest status;
regenerate with `python scripts\build_capabilities.py`.

## Licence and acknowledgements

This repository has **no licence file yet**; all rights reserved by default
(owner's decision). No code, tests or docs were copied from other
repositories. Ideas were taken and reimplemented from MIT / Apache-2.0
projects: U-C4N/Autocad-MCP (COM thread with timeouts, plot handling, path
checks, capability refusals), beiming183-cloud/AutoCAD-MCP (error codes with
recovery hints, state vocabulary, document pinning),
LokmenoWer/best-cad-mcp (SDK v2 threading, annotations),
thewisekape/autocad-mcp (QC checks), Psalmustrack/lambdacad-mcp (verification
by measurement), Jjo37/new-acad (bounded summaries). Runtime dependencies: MCP
Python SDK (MIT), pywin32 (PSF), ezdxf (MIT, optional).
