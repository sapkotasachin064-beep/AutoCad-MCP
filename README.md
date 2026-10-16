# AutoCAD MCP Server

MCP server that drives AutoCAD 2021+ over COM on Windows.

## Scope

- **Target**: Windows + AutoCAD 2021 or newer. AutoCAD LT is out of scope (LT has
  no COM/ActiveX automation API).
- **V0.1.0**: minimal end-to-end path -- check AutoCAD state, create a drawing, draw
  one line, save it.
- **V0.2.0** (this version): drawing creation and geometry, layers, entity editing,
  highlighting, and a local SQLite database of scanned entities with a read-only
  query tool. All 15 tools operate on real AutoCAD entities through the COM
  backend in `src/MCP/autocad/connection.py` -- there is no simulated/offline mode.

## Requirements

- Windows, AutoCAD 2021 or newer installed
- Python 3.10+

```bash
pip install -r requirements.txt
```

## Run

```bash
python src/MCP/server.py
```

Runs over stdio, for use as an MCP server from a compatible client.

### Claude Code

Add to your MCP config (`.mcp.json` or via `claude mcp add`):

```json
{
  "mcpServers": {
    "autocad-mcp": {
      "command": "python",
      "args": ["C:/path/to/project/src/MCP/server.py"]
    }
  }
}
```

### OpenCode

Add the same `command`/`args` pair under OpenCode's MCP server configuration
(`opencode.json` `mcp` section, or equivalent). The server has no OpenCode-specific
code path; `autocad_get_status` reports a best-effort `opencode` detection flag
(`autocad/opencode.py`) based on environment variables, nothing more.

## Units and coordinates

Every point argument is `[x, y]` or `[x, y, z]` in the **active drawing's current
drawing units** (whatever `INSUNITS`/the current UCS says they are) -- the server
never assumes millimeters, inches, or any other unit, and never converts between
units. `z` defaults to `0.0` when omitted. Angles for `rotate_entity` and
`draw_text`'s `rotation_degrees` are in **degrees, counterclockwise-positive when
viewed from +Z**, matching AutoCAD's own `Rotate()` COM method and `ROTATE`
command convention; this is not reinterpreted for a rotated UCS.

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

Tools not in this list (`get_all_tables`, `get_table_schema`, `query_and_highlight`,
`draw_device_connection`) exist in the reference repo but are out of this
milestone's scope (see the request's section 9) and were not ported.

## Database

- Location: `AUTOCAD_MCP_DB_PATH`, default `<output dir>/autocad_mcp.db`.
- Schema (`src/MCP/autocad/db.py`): `drawings` (one row per drawing identity) and
  `entities` (one row per scanned entity, `UNIQUE(drawing_id, handle)`), migrated
  via `PRAGMA user_version`.
- **Drawing identity** (`src/MCP/autocad/identity.py`): AutoCAD's COM `Document`
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
  `connection.get_connected_app()` boundary every tool goes through, but 2021-2023
  and 2025+ are not individually verified -- see "Compatibility detection" in
  Testing below for exactly what *is* and isn't claimed.
- Under rapid, back-to-back automated calls, AutoCAD's own dynamic COM dispatch
  can transiently raise `AttributeError` for a property that genuinely exists
  (observed live, see `connection._retry_com`'s docstring); this is retried the
  same way a busy `RPC_E_CALL_REJECTED` is. If AutoCAD's UI focus/active document
  shifts for reasons outside this server's control (another window, a modal, the
  user clicking around) between two tool calls, each tool still reports which
  `drawing_identity` it actually acted on in its result -- check that field if a
  multi-step workflow produces a surprising result.

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
  AutoCAD) and checks exactly the 18 expected tools are registered once each,
  with the expected required/optional argument schemas.
- **`test_e2e_mcp.py`**: spawns `server.py` as a real subprocess and talks to it
  over stdio with the official `mcp` client SDK -- true end-to-end discovery
  (`list_tools`) and invocation (`call_tool`), including that a validation error
  comes back as `is_error=True` rather than a crash. Does not require AutoCAD.
- **`test_integration_autocad.py`**: real COM calls against a **running** AutoCAD
  2021+. Skipped (reported as skipped, not faked as passing) when AutoCAD isn't
  running/connected/a supported release. To run it for real:

  ```bash
  python -c "import sys; sys.path.insert(0,'src/MCP'); from autocad import connection; print(connection.launch_and_wait())"
  python -m pytest tests/test_integration_autocad.py -v
  ```

  Each test uses its own fresh, unsaved drawing (closed without saving in
  teardown) and an isolated temp database, so it won't touch real drawings or the
  real `autocad_mcp.db`.
