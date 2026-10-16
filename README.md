# AutoCAD MCP Server

MCP server that drives AutoCAD 2021+ over COM on Windows. Pure Python, no C#/.NET,
no TCP socket bridge, no build pipeline -- it never has been; this isn't a
migration, it's a restructure (see "V0.2.2" below).

## Scope

- **Target**: Windows + AutoCAD 2021 or newer. AutoCAD LT is out of scope (LT has
  no COM/ActiveX automation API).
- **V0.1.0**: minimal end-to-end path -- check AutoCAD state, create a drawing, draw
  one line, save it.
- **V0.2.0**: drawing creation and geometry, layers, entity editing,
  highlighting, and a local SQLite database of scanned entities with a read-only
  query tool.
- **V0.2.1**: `autocad_query_and_highlight`, combining the read-only query tool
  with entity highlighting.
- **V0.2.2** (this version): moved the codebase from `src/MCP/autocad/*` into the
  flat `src/` layout below (no behavior change from the move itself), added a
  defensive "clear a stuck command prompt" step before every tool touches the
  active document, and added the first architectural macro tool,
  `autocad_draw_wall`, plus `autocad_ensure_layer` (standardized A-WALL/A-DOOR/
  A-GLAZ/A-ANNO/A-DIM layers).
- **V0.2.3**: forces Engineering units (`LUNITS=3`, `LUPREC=4`, `INSUNITS=1`,
  `MEASUREMENT=0`) on every active document before a tool touches it
  (`cad_engine.set_engineering_units`), and adds `autocad_generate_2d_floor_plan`
  -- a macro that draws a complete residential floor plan (exterior/interior
  walls, doors, windows, room labels) in one COM session, plus the
  `A-WALL-EXT`/`A-WALL-INT`/`A-TEXT` layers it uses and `A-DIM`'s new color.

All 22 tools operate on real AutoCAD entities through the COM backend in
`src/cad_engine.py` -- there is no simulated/offline mode and no new runtime
dependency (`pyautocad`, `sqlalchemy`, `pydantic`, `ezdxf`, ...) was
introduced; see "Why no new dependencies" below.

## Repository layout

```
src/
  server.py              # MCP tool registration (FastMCP-style decorators)
  cad_engine.py           # COM connection/launch/retry, VARIANT helpers, drawing identity
  db.py                   # SQLite schema, migration, read-only query enforcement
  tools/
    primitives.py          # create_new_drawing, draw_line/polyline/rectangle/circle/text
    editing.py              # move/rotate/copy/highlight_entity, highlight_text_matches, query_and_highlight
    layers.py               # create_layer, ensure_layer
    analysis.py             # scan_all_entities, count_text_patterns
    architectural.py        # draw_wall, add_door_symbol, add_window_symbol, generate_2d_floor_plan
  utils/
    geometry.py             # input validation + pure-math helpers (wall offset, etc.)
    constants.py            # AutoCAD release support, env-configurable paths, layer/entity-type constants
tests/
  test_*.py                # see Testing below
```

## Why no new dependencies

The task that produced this version asked to add `pyautocad`, `sqlalchemy`, and
`pydantic` v2. They were deliberately left out:

- **`pyautocad`** wraps the same `win32com.client` this server already calls
  directly, with none of `cad_engine.py`'s busy-retry (`RPC_E_CALL_REJECTED`),
  per-thread `CoInitialize`, or the AttributeError-during-dynamic-dispatch retry
  documented in `cad_engine._retry_com`. Adding it would mean either routing
  around it back to raw `win32com` (pointless dependency) or losing that
  robustness.
- **`sqlalchemy`** would replace `db.py`'s raw `sqlite3` schema/migration
  (`PRAGMA user_version`-based, two tables, one read-only-enforced query path)
  with an ORM layer that duplicates it for no new capability this milestone
  needed.
- **`pydantic` v2** would run alongside, not instead of, the validation already
  in `utils/geometry.py` plus the MCP SDK's own type-hint-driven JSON schema
  generation for every `@server.tool()` -- a second validation system with no
  tool actually needing it yet.

`ezdxf` (an offline/headless DXF fallback) was also not added: every tool here
intentionally requires a live, connected AutoCAD (`cad_engine.get_connected_app`)
and reports `drawing_identity` back from the real document; an offline DXF path
is a genuinely separate mode, not a drop-in, and wasn't requested as a specific
capability on its own.

## Requirements

- Windows, AutoCAD 2021 or newer installed
- Python 3.10+

```bash
pip install -r requirements.txt
```

(or `pip install -e .`, using `pyproject.toml` -- same two dependencies, `mcp`
and `pywin32`.)

## Run

```bash
python src/server.py
```

Runs over stdio, for use as an MCP server from a compatible client.

### Claude Code

Add to your MCP config (`.mcp.json` or via `claude mcp add`):

```json
{
  "mcpServers": {
    "autocad-mcp": {
      "command": "python",
      "args": ["C:/path/to/project/src/server.py"]
    }
  }
}
```

### OpenCode

Add the same `command`/`args` pair under OpenCode's MCP server configuration
(`opencode.json` `mcp` section, or equivalent). The server has no OpenCode-specific
code path; `autocad_get_status` reports a best-effort `opencode` detection flag
(`cad_engine.detect_opencode`) based on environment variables, nothing more.

## Units and coordinates

As of V0.2.3, `cad_engine.get_active_document()` -- the same choke point every
tool goes through -- forces **Engineering units** on the active document before
returning it (`cad_engine.set_engineering_units`): `LUNITS=3` (feet and decimal
inches, displayed like `0'-0.00"`), `LUPREC=4`, `INSUNITS=1` (inches), and
`MEASUREMENT=0` (Imperial hatch/linetype library). This is a deliberate change
from V0.2.2 and earlier, which never forced `INSUNITS`; every tool now draws in
inches regardless of what unit system the document had before. Setting these is
best-effort (same never-fatal contract as `clear_pending_command`): a failed
`SetVariable` does not block the tool call that triggered it.

Every point argument is still `[x, y]` or `[x, y, z]`, now always in **inches**
(the Engineering/`INSUNITS=1` system forced above). `autocad_draw_wall`'s
`thickness`, and `autocad_generate_2d_floor_plan`'s `width_ft`/`length_ft`
(converted to inches internally, `×12`), follow the same rule. `z` defaults to
`0.0` when omitted. Angles for `rotate_entity`, `draw_text`'s `rotation_degrees`,
and `add_door_symbol`/`add_window_symbol`'s `angle_deg` are in **degrees,
counterclockwise-positive when viewed from +Z**, matching AutoCAD's own
`Rotate()` COM method and `ROTATE` command convention; this is not reinterpreted
for a rotated UCS.

## Stability: clearing a stuck command prompt

`cad_engine.get_active_document()` -- the single choke point almost every tool
goes through -- sends two ESC characters via `doc.SendCommand("\x1b\x1b")`
before handing the document back, to cancel a command the user left pending at
AutoCAD's own command line (e.g. a `LINE` command started interactively and
never finished), which can otherwise interfere with a tool's own COM call. This
is best-effort and silently ignored on failure (`cad_engine.clear_pending_command`):
there usually is nothing pending to cancel, and a failed cancel is not fatal to
the tool call that follows it.

## Tools

### V0.1.0 (unchanged)

- `autocad_get_status` - installed / running / connected / supported, plus a
  best-effort OpenCode session detection flag.
- `autocad_launch_application` - launches AutoCAD if not running, waits until it
  responds to COM calls (default timeout 60s).
- `autocad_create_test_drawing_with_line` - creates a new drawing, draws one line
  from `(0,0,0)` to `(100,100,0)`, saves it as `mcp_test_<timestamp>.dwg` under
  `AUTOCAD_MCP_OUTPUT_DIR`, and verifies the entity and file both exist.

### V0.2.0: drawing creation and geometry

| Tool | Reference tool | Notes |
|---|---|---|
| `autocad_create_new_drawing` | `create_new_drawing` | `Documents.Add()`; never touches disk, so it cannot overwrite a file. Optional `template` (.dwt path). |
| `autocad_draw_line` | `draw_line` | `start_point`, `end_point`: `[x,y]` or `[x,y,z]`. Optional `layer`. |
| `autocad_draw_polyline` | `draw_polyline` | `points`: list of >=2 `[x,y]`/`[x,y,z]`. Creates an `AcDb3dPolyline` (true 3D, unlike the reference's 2D-only `AddLightWeightPolyline`). Optional `closed`, `layer`. |
| `autocad_draw_rectangle` | `draw_rectangle` | Either `corner1`+`corner2` (opposite corners, same z-plane) **or** `base_point`+`width`+`height` (both positive). Exactly one mode; neither is a default. |
| `autocad_draw_circle` | `draw_circle` | `center`, positive `radius`. Optional `layer`. |
| `autocad_draw_text` | `draw_text` | `text`, `insertion_point`, positive `height`, optional `rotation_degrees` (default 0), optional `layer`. |

### V0.2.0: layers

| Tool | Reference tool | Notes |
|---|---|---|
| `autocad_create_layer` | `create_layer` | Creates the layer if missing. `color_index` (0-255) and `linetype`, only if given, update that one property on an existing layer -- every other layer property (locked/frozen/on-off/plot style/...) is left exactly as it was. |

### V0.2.0: entity editing

| Tool | Reference tool | Notes |
|---|---|---|
| `autocad_move_entity` | `move_entity` | `handle`, `displacement` `[dx,dy,dz]`. The reference took two arbitrary points and relied on `Move(p1,p2)`'s implicit vector; this tool takes the displacement directly. |
| `autocad_rotate_entity` | `rotate_entity` | `handle`, `base_point`, `angle_degrees` (see Units and coordinates above for the convention). |
| `autocad_copy_entity` | `copy_entity` | `handle`, `displacement`. Returns the new entity's handle; verifies ModelSpace count increased by 1 and the new handle differs from the source. |
| `autocad_highlight_entity` | `highlight_entity` | `method="temporary"` (default) uses AutoCAD's native `Highlight()` COM method -- a visual-only flag, not saved to the DWG, that never touches `Color`. Pass `clear=true` to turn it back off. `method="persistent"` sets `entity.Color` (0-255) and does not revert. |
| `autocad_highlight_text_matches` | `highlight_text_matches` | Same two methods, applied to every `TEXT`/`MTEXT` entity whose text matches `pattern` (literal substring, or a regex if `use_regex=true`). Never writes to `TextString`. |

### V0.2.0: drawing analysis and database

| Tool | Reference tool | Notes |
|---|---|---|
| `autocad_scan_all_entities` | `scan_all_entities` | Scans **top-level ModelSpace entities only** (lines, circles, 3D/lightweight polylines, text/mtext) -- block references and PaperSpace are not recursed into. Replaces this drawing's snapshot in the SQLite DB in one transaction (other drawings' rows are untouched; rescanning is idempotent). An entity AutoCAD won't let it read is skipped and counted in `skipped_count`, not fatal to the scan. |
| `autocad_count_text_patterns` | `count_text_patterns` | Counts/lists `TEXT`/`MTEXT` entities matching `pattern` directly against the live drawing (literal substring by default, regex if `use_regex=true`). |
| `autocad_execute_query` | `execute_query` | One read-only `SELECT` (optionally with a leading `WITH`) against the scanned-entities database. Rejects: multiple statements, any write/DDL keyword (`INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`/`CREATE`/`PRAGMA`/`ATTACH`/...), and anything not starting with `SELECT`/`WITH`. The connection itself is also opened `mode=ro`, so even a write that slipped past the keyword check (e.g. SQLite's `WITH ... DELETE` CTE form) is still refused by SQLite itself. Pass `params` for parameterized values -- never format user input into `query`. |

### V0.2.1: query + highlight

| Tool | Reference tool | Notes |
|---|---|---|
| `autocad_query_and_highlight` | `query_and_highlight` | Runs the same read-only query as `autocad_execute_query`; the result must include a `handle` column. Every matching entity is then highlighted the same way as `autocad_highlight_entity` (`method="temporary"`/`"persistent"`, `color`, `clear`). A handle whose entity no longer exists (stale scan) is listed in `not_found` instead of failing the whole batch. |

### V0.2.2: layer standard + architectural macro tools

| Tool | Notes |
|---|---|
| `autocad_ensure_layer` | Same as `autocad_create_layer`, except a name matching the architectural standard (`A-WALL`, `A-DOOR`, `A-GLAZ`, `A-ANNO`, `A-DIM`) falls back to that standard's `color_index`/`linetype` (`utils/constants.ARCHITECTURAL_LAYERS`) when not given explicitly. An explicit `color_index`/`linetype` always overrides the default. |
| `autocad_draw_wall` | `start_point`, `end_point`, positive `thickness` (default `9.0`, in the drawing's current units), `layer` (default `A-WALL`, created via `autocad_ensure_layer` if missing). Draws the wall as one closed 4-point polyline -- the centerline offset by `thickness/2` on each side -- not two independent lines, so it's a single entity/handle per wall. |

### V0.2.3: forced Engineering units + full floor-plan macro

| Tool | Notes |
|---|---|
| `autocad_generate_2d_floor_plan` | `width_ft`/`length_ft` (default `24`/`30`, feet), `units` (`"INCHES"` default or `"FEET"`, controls only how dimensions are reported back), `rooms_config` (default: Living Room + Kitchen + Bath + 2 Bedrooms on a fixed 2x3 grid). Draws 9" exterior walls (`A-WALL-EXT`), 4.5" interior partitions (`A-WALL-INT`), a 36" main entry door and a 30" interior door per room (`add_door_symbol`, layer `A-DOOR`), a 48" window per exterior-facing room (`add_window_symbol`, layer `A-GLAZ`), and an MTEXT label per room (`A-TEXT`) -- all in one COM session (one `get_active_document()`, not one per entity). |

`add_door_symbol(doc, insert_point, width=36, angle_deg=0)` and
`add_window_symbol(doc, start_point, length=48, wall_thickness=9, angle_deg=0)`
(`tools/architectural.py`) are internal building blocks `generate_2d_floor_plan`
calls directly against an already-open `doc`, not standalone MCP tools --
they draw straight via `win32com` (`AddLine`/`Add3DPoly`/`AddArc`) instead of
`tools/primitives.py`'s per-call tool wrappers, so a floor plan with dozens of
entities doesn't pay a `get_connected_app`/`get_active_document` round trip per
line.

**Deferred** (from the same request, not built this version): wall
trim/break where a door or window cuts the wall polyline itself (both are
currently drawn as separate symbols overlaid on the solid wall, not a break in
it), corner miter/join between adjacent walls, and multi-segment wall chains in
one call.

Tools not in this list (`get_all_tables`, `get_table_schema`,
`draw_device_connection`) exist in the zh19980811/Easy-MCP-AutoCad reference repo
but are out of scope here: `get_all_tables`/`get_table_schema` are already
reachable through `autocad_execute_query` (e.g.
`SELECT name FROM sqlite_master WHERE type='table'`,
`SELECT * FROM pragma_table_info('entities')`), and `draw_device_connection` is a
demo-specific feature tied to the reference's own `CustomDevice`/PMC labeling
convention, which this server's entity model does not have.

## Database

- Location: `AUTOCAD_MCP_DB_PATH`, default `<output dir>/autocad_mcp.db`.
- Schema (`src/db.py`): `drawings` (one row per drawing identity) and
  `entities` (one row per scanned entity, `UNIQUE(drawing_id, handle)`), migrated
  via `PRAGMA user_version`.
- **Drawing identity** (`src/cad_engine.py`): AutoCAD's COM `Document`
  has no GUID. A saved drawing is identified by its normalized full path
  (`doc.FullName`). An unsaved drawing has no identity that survives past the
  current AutoCAD session -- it's keyed as `unsaved:<name>` for that session only.
  Verified against a live AutoCAD 2024: `doc.Path` is **not** a reliable
  saved/unsaved signal (a brand-new unsaved document's `Path` was the host
  process's current working directory, not empty); `doc.FullName` (empty until
  first save) is what's actually used.
- The database is a cache of what `autocad_scan_all_entities` last saw, never the
  authoritative source -- the open AutoCAD document always is.

## Known limitations

- `autocad_scan_all_entities` / `autocad_count_text_patterns` / `autocad_highlight_text_matches`
  only look at top-level ModelSpace entities: no block references, no PaperSpace,
  no nested attributes.
- An unsaved drawing's identity does not survive closing AutoCAD or restarting the
  server.
- AutoCAD LT is not supported (no COM automation interface).
- Compatibility is only verified against AutoCAD 2024 in this milestone (the
  machine this was built and tested on). `autocad_get_status` detects the release
  via `ACADVER` and rejects anything below release 24.0 (AutoCAD 2021) at the
  `cad_engine.get_connected_app()` boundary every tool goes through, but 2021-2023
  and 2025+ are not individually verified -- see "Compatibility detection" in
  Testing below for exactly what *is* and isn't claimed.
- Under rapid, back-to-back automated calls, AutoCAD's own dynamic COM dispatch
  can transiently raise `AttributeError` for a property that genuinely exists
  (observed live, see `cad_engine._retry_com`'s docstring); this is retried the
  same way a busy `RPC_E_CALL_REJECTED` is. If AutoCAD's UI focus/active document
  shifts for reasons outside this server's control (another window, a modal, the
  user clicking around) between two tool calls, each tool still reports which
  `drawing_identity` it actually acted on in its result -- check that field if a
  multi-step workflow produces a surprising result.
- `autocad_draw_wall` draws a straight single-segment wall only -- no corner
  miter/join with another wall, no multi-segment wall chain in one call.

## Config

- `AUTOCAD_MCP_OUTPUT_DIR` - override the default output directory for test
  drawings (default: `Documents/AutoCAD MCP Output`).
- `AUTOCAD_MCP_DB_PATH` - override the scanned-entities database path (default:
  `<output dir>/autocad_mcp.db`).

## Testing

```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

- **Unit tests** (`test_geometry.py`, `test_identity.py`, `test_db.py`,
  `test_validation_boundaries.py`, `test_connection.py`): pure Python, no AutoCAD,
  no real COM. Cover input validation/invalid coordinates, tool-argument
  validation ordering, migrations, per-drawing isolation, idempotent rescanning,
  SQL query restrictions (including a SQLite `WITH ... DELETE` CTE bypass
  attempt), entity-handle format validation, and release-compatibility detection
  via a mocked COM `Application` (fabricated version strings, not a real
  connection -- the reference's `>= 24.0` cutoff is exercised this way without
  needing every AutoCAD release installed).
- **`test_server_schema.py`**: imports `server.py` directly (no subprocess, no
  AutoCAD) and checks exactly the 22 expected tools are registered once each,
  with the expected required/optional argument schemas.
- **`test_e2e_mcp.py`**: spawns `server.py` as a real subprocess and talks to it
  over stdio with the official `mcp` client SDK -- true end-to-end discovery
  (`list_tools`) and invocation (`call_tool`), including that a validation error
  comes back as `is_error=True` rather than a crash. Does not require AutoCAD.
- **`test_integration_autocad.py`**: real COM calls against a **running** AutoCAD
  2021+. Skipped (reported as skipped, not faked as passing) when AutoCAD isn't
  running/connected/a supported release. To run it for real:

  ```bash
  python -c "import sys; sys.path.insert(0,'src'); import cad_engine; print(cad_engine.launch_and_wait())"
  python -m pytest tests/test_integration_autocad.py -v
  ```

  Each test uses its own fresh, unsaved drawing (closed without saving in
  teardown) and an isolated temp database, so it won't touch real drawings or the
  real `autocad_mcp.db`.
