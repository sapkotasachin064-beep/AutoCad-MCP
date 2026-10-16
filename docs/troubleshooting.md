# Troubleshooting

Every tool failure is a JSON envelope with a `code` and a
`recommended_action`; start from the code.

## Server does not start in the client

| Symptom | Cause | Fix |
|---|---|---|
| `spawn python ENOENT`, "command not found" | the client cannot find `python` | use the absolute path of the venv's `python.exe` in the client config |
| `ModuleNotFoundError: No module named 'mcp'` / `'win32com'` | packages installed into a different Python | run `"<that python>" -c "import mcp, win32com"`; install with that interpreter |
| `ModuleNotFoundError: No module named 'mcp.server.mcpserver'` | MCP SDK 1.x installed | `pip install "mcp>=2.3,<3"` |
| Client reports a startup timeout | first start compiles bytecode; importing the SDK took ~6 s on the dev machine | raise the client's startup timeout (Codex: `startup_timeout_sec = 30`) |
| `E_INVALID_CONFIG` at start | bad `AUTOCAD_MCP_TOOLSETS` value | use names from [installation.md](installation.md#environment-variables) |
| Too many tools for the client | 64 tools advertised | `AUTOCAD_MCP_TOOLSETS=core,drawing,query` (any subset) |

## AutoCAD connection

| Code | Meaning | What to do |
|---|---|---|
| `E_AUTOCAD_NOT_INSTALLED` | no `AutoCAD.Application` ProgID | install full AutoCAD 2021+ (LT has no COM) or use the `dxf` backend |
| `E_AUTOCAD_NOT_RUNNING` | AutoCAD process absent | `autocad_launch_application`, or start AutoCAD yourself |
| `E_AUTOCAD_NOT_RESPONDING` | process up but COM rejected the call | close modal dialogs (licence, recovery, "save changes?"), finish or Esc the active command, retry |
| `E_AUTOCAD_UNSUPPORTED_RELEASE` | older than AutoCAD 2021 | upgrade, or use the `dxf` backend |
| `E_COM_BUSY` | your call waited behind a slow call and was cancelled; nothing was sent | retry |
| `E_COM_TIMEOUT` | a started call did not finish in time | **look at the drawing first** -- the call may still complete inside AutoCAD; then retry or raise `AUTOCAD_MCP_COM_TIMEOUT` |

Stale `*.dwl` / `*.dwl2` files beside a drawing are AutoCAD lock files left by
a crash or forced close; AutoCAD manages them. Delete them only when no
AutoCAD has that drawing open.

## Documents

| Code | Meaning | What to do |
|---|---|---|
| `E_NO_ACTIVE_DOCUMENT` | no drawing open | `autocad_create_new_drawing` or `autocad_open_drawing` |
| `E_DOCUMENT_CHANGED` | the session is pinned and another drawing is active; nothing was changed | activate the pinned drawing (`autocad_activate_drawing`) or `autocad_unpin_document` |
| `E_DOCUMENT_PINNED` | creating/opening/activating would leave the pinned drawing | pass `pin=true` to move the pin, or unpin |
| `E_DOCUMENT_NOT_FOUND` | no open drawing has that identity | copy an identity from `autocad_list_drawings` |
| `E_UNSAVED_CHANGES` | close/replace would lose work | `autocad_save_drawing`, or `discard_changes=true` when you mean it |
| identity changed after saving | an unsaved drawing gets a path identity on its first save | pins follow automatically; re-read `drawing_identity` |

## Units

* Drawings switched to inches: V0.2.x behaviour, kept as the default
  (`AUTOCAD_MCP_UNITS=engineering`) but since V0.3.0 applied only by tools that
  change the drawing, and reported as a `units_changed` notice. Use
  `autocad_set_drawing_units("metric_mm")` for a metric project or
  `AUTOCAD_MCP_UNITS=preserve` to never touch units.
* `E_UNITS_MISMATCH`: the drawing's `INSUNITS` is unitless; set units first.

## Files

| Code | Meaning | What to do |
|---|---|---|
| `E_OUTPUT_EXISTS` | target exists | choose another name or `overwrite=true` |
| `E_OUTPUT_PATH_REJECTED` | `..`, UNC, `\\?\`, a system folder, or outside `AUTOCAD_MCP_ALLOWED_DIRS` | use a normal local path inside the allowed folders |
| `E_FILE_NOT_FOUND` | input missing, or the output folder does not exist | create the folder (only the server's own output folder is created automatically) |
| `E_PLOT_FAILED` | AutoCAD refused the plot | check the layout has something in its plot area, that `DWG To PDF.pc3` exists, and use a paper name from the error's `candidates` |
| `E_DEPENDENCY_MISSING` | headless feature without its package | `pip install -e ".[dxf]"` (ezdxf) or `pip install matplotlib` (previews) |
| `E_UNSUPPORTED_BACKEND` | not available on this backend (e.g. DWG headlessly, plotting headlessly) | read `message`; use the other backend or the suggested tool |

## Recovering an interrupted job

When a call ends in `E_COM_TIMEOUT`, `E_VERIFICATION_FAILED` or a lost
connection in the middle of a generator:

1. `autocad_list_drawings` -- is the intended drawing still open and active?
2. `autocad_drawing_summary` -- compare counts by layer with what you expected
   (generators draw on their own layers: `A-WALL-EXT`, `A-WALL-INT`, `A-DOOR`,
   `A-GLAZ`, `A-TEXT`, `A-DIM` for plans; `S-GRID`, `S-GRID-IDEN`, `S-COLS`,
   `S-ANNO-DIMS` for grids; `A-FLOR-STRS`, `A-ANNO-NOTE` for stairs;
   `G-ANNO-TTLB`, `G-ANNO-TTLB-TEXT` for sheets).
3. `autocad_list_entities(layers=[...])` lists what was drawn; remove partial
   output with `autocad_delete_entities` (dry run first) or AutoCAD's own
   Undo.
4. Re-run the generator, ideally after a `dry_run=true` to confirm the plan.

Generators do not yet wrap their work in a single undo group or report the
handles drawn before a failure (both catalogued as planned).
