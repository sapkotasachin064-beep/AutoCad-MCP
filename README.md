# AutoCAD MCP Server

An MCP (Model Context Protocol) server that lets AI assistants -- Claude Code,
OpenCode, Codex CLI, Claude Desktop and other MCP clients -- draft, edit,
inspect and check AutoCAD drawings. It drives a running **AutoCAD 2021+ on
Windows over COM**, or edits **DXF files headlessly** with ezdxf when no
AutoCAD is available.

Version **0.3.0**. Drafting aid for students and drafters: nothing here is a
structural design, a building-code check, or a professional bill of
quantities.

## At a glance

| | |
|---|---|
| Public MCP tools | **70**, in 11 toolsets ([tool reference](docs/tools.md)) |
| MCP resources / prompts | 3 / 3 |
| Backends | `com` (live AutoCAD 2021+, Windows) and `dxf` (headless ezdxf) |
| Catalogued capabilities | **650**: 62 live-verified, 165 tested, 26 implemented without a dedicated test, 397 planned ([catalog](docs/feature-catalog.md)) |
| Tests | 322: 302 pass without AutoCAD, 20 live tests skip; live results recorded for 19 tests on AutoCAD 2024 (the civil live test is not yet run) |

"Verified" means a live test asserted it on AutoCAD 2024 (R24.3) in this
project ([results](docs/testing.md#live-autocad-results)). "Tested" means
automated tests only (unit, recorded-fake COM, headless DXF files, stdio
end-to-end, golden regression). Other AutoCAD releases have not been run.

## What it can do (implemented)

* **Session and safety** -- status and launch; capability report; one dedicated
  COM thread with timeouts; document pinning (a tab switch cannot redirect
  edits); JSON error envelopes with stable codes and recovery hints; every
  change reports `executed / verified / saved` separately; dry runs for
  deletes and generators; output paths validated, no overwrite without
  `overwrite=true`; no raw command/LISP execution tool.
* **Documents** -- new (optionally from a template), open (read-only by
  default), save / save-as DWG R2000-R2018 or DXF with SHA-256 evidence, close
  with an unsaved-changes guard, list, activate, set units (engineering,
  architectural, metric mm/m).
* **Drawing and editing** -- lines, 3D polylines, rectangles, circles, arcs,
  TEXT, MTEXT; move, rotate, copy, scale, mirror, offset, rectangular array,
  delete (dry run first), set layer/color/linetype/lineweight, highlight.
* **Annotation, layers, blocks** -- aligned/linear dimensions checked against
  the geometry; hatches with pattern read-back; layer list and properties with
  linetype auto-load; block list, insert with attributes, read/update
  attributes.
* **Inspection** -- drawing summary (units, extents, counts by type and layer),
  filtered and paginated entity listing, entity detail, SQLite scan + read-only
  SQL, text search.
* **Residential and civil drafting** -- floor plans from explicit room
  rectangles (walls, doors connecting every room, windows, area labels, overall
  dimensions, room/door/window schedules); the V0.2.3 2x3 floor plan
  (reproduced entity-for-entity); structural column grids with bubbles,
  column marks and dimensions; stair design with stated limits and stair plans;
  sheet borders and title blocks at a plot scale.
* **Analysis and output** -- drafting checks (zero-length, duplicates, empty
  text, layer 0, open wall outlines, layer naming), quantity takeoff per layer
  (lengths, areas, walls, hatches, blocks), JSON/CSV/Markdown reports, DXF
  revision comparison, DXF file validation, DXF export without renaming the
  drawing, PDF plotting that checks the file on disk (live backend),
  PNG/PDF/SVG previews (headless, needs matplotlib).

Planned work (399 catalogued entries, e.g. undo groups per call, polar arrays,
trim/extend, layouts and viewports, leaders, Civil 3D surfaces/alignments,
survey computations, plumbing/electrical/P&ID drafting, an AutoCAD LT backend)
is listed in [docs/feature-catalog.md](docs/feature-catalog.md) and is **not**
available yet.

## Supported environments

| | |
|---|---|
| OS | Windows 10/11 (tested on 11). Headless backend designed for any OS, tested on Windows only. |
| AutoCAD | 2021 (R24.0) - 2027 (R26.0) accepted; live tests pass on 2024 (R24.3); other releases not run. Full AutoCAD only -- **LT has no COM** and is not supported. |
| Python | 3.10+ declared; tested on 3.14.7 |
| MCP SDK | `mcp>=2.3,<3` (tested 2.3.0) |
| Headless | `ezdxf>=1.3` (tested 1.4.4); previews need `matplotlib` (not tested) |

Details: [docs/compatibility.md](docs/compatibility.md), [docs/backends.md](docs/backends.md).

## Architecture

```
MCP client --stdio--> src/server.py (70 tools, error envelopes, state blocks, toolsets)
                         |
                  src/backends/  com.py  -> src/tools/*  -> COM thread -> AutoCAD
                                 dxf.py  -> ezdxf document in memory
                         |
                  src/domain/  (pure: units, floor plans, grids, stairs, sheets, QC, takeoff, diff)
                  src/core/    (errors, COM executor, session/pin, registry, paths, evidence, reports)
```

Generators build a plan first, then draw it through one emitter on either
backend and verify the entity count. Full description:
[docs/architecture.md](docs/architecture.md).

## Install (Windows)

Prerequisites: Python 3.10+, Git, and for live use a full AutoCAD 2021+.

```powershell
git clone https://github.com/sapkotasachin064-beep/AutoCad-MCP.git
cd AutoCad-MCP
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dxf.txt   # optional: headless backend, DXF compare/validate
```

Environment variables (all optional) -- full table in
[docs/installation.md](docs/installation.md#environment-variables):

| Variable | Default | |
|---|---|---|
| `AUTOCAD_MCP_BACKEND` | `com` | `com` or `dxf`; fixed per process, no automatic fallback |
| `AUTOCAD_MCP_UNITS` | `engineering` | units preset drawing tools apply; `preserve` = never change units |
| `AUTOCAD_MCP_COM_TIMEOUT` | `120` | seconds per live call |
| `AUTOCAD_MCP_TOOLSETS` | `all` | e.g. `core,drawing,query` to advertise fewer tools |
| `AUTOCAD_MCP_OUTPUT_DIR` | `Documents\AutoCAD MCP Output` | where relative output paths go |
| `AUTOCAD_MCP_ALLOWED_DIRS` | unset | confine every file path a tool accepts to these folders (`;`-separated) |

## Start the server

```powershell
python src\server.py
```

It speaks MCP over stdio and is normally started by your client. After
`pip install -e .` the same server runs as `autocad-mcp`.

## Connect a client

Use absolute paths. Details, verification status and file formats:
[docs/client-integrations.md](docs/client-integrations.md).

**Claude Code** (claude 2.1.300 generated and parsed the same entry with
`--scope project` in a scratch folder; a connected session was not tested):

```powershell
claude mcp add autocad --scope user -e AUTOCAD_MCP_BACKEND=com -- "C:\path\to\AutoCad-MCP\.venv\Scripts\python.exe" "C:\path\to\AutoCad-MCP\src\server.py"
```

**OpenCode** (opencode 2.0.31 generated the config in a scratch folder; a
connected session was not tested):

```powershell
opencode mcp add autocad --env AUTOCAD_MCP_BACKEND=com -- "C:\path\to\AutoCad-MCP\.venv\Scripts\python.exe" "C:\path\to\AutoCad-MCP\src\server.py"
```

**Codex CLI** (from OpenAI's docs; not tested here) -- `~/.codex/config.toml`:

```toml
[mcp_servers.autocad]
command = 'C:\path\to\AutoCad-MCP\.venv\Scripts\python.exe'
args = ['C:\path\to\AutoCad-MCP\src\server.py']
startup_timeout_sec = 30
tool_timeout_sec = 300
```

**Claude Desktop** (not tested here) -- `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{ "mcpServers": { "autocad": {
    "command": "C:\\path\\to\\AutoCad-MCP\\.venv\\Scripts\\python.exe",
    "args": ["C:\\path\\to\\AutoCad-MCP\\src\\server.py"] } } }
```

Check any client by asking it to call `autocad_get_status`.

## Live AutoCAD

1. Start AutoCAD (or call `autocad_launch_application`).
2. `autocad_get_status` -> `connected: true`, `supported: true`, `release_year`.
3. `autocad_create_new_drawing` with `pin: true`, then draw; finish with
   `autocad_save_drawing` (`path` for the first save). Results say
   `state.saved: false` until you do.

## Headless DXF

Set `AUTOCAD_MCP_BACKEND=dxf` (with ezdxf installed). The same tools work on
one in-memory DXF: `autocad_create_new_drawing` or `autocad_open_drawing`
(DXF only), draw, then `autocad_save_drawing(path="plan.dxf")`. DWG,
plotting, highlighting and launching AutoCAD are refused with the reason.

## Example: a small house plan

```json
{"tool": "autocad_set_drawing_units", "arguments": {"preset": "metric_mm"}}
{"tool": "autocad_generate_floor_plan", "arguments": {
  "unit": "m",
  "rooms": [
    {"name": "Living",  "x": 0,   "y": 0,   "width": 4.5, "depth": 4.0},
    {"name": "Kitchen", "x": 4.5, "y": 0,   "width": 3.0, "depth": 4.0},
    {"name": "Bedroom", "x": 0,   "y": 4.0, "width": 4.5, "depth": 3.6},
    {"name": "Bath",    "x": 4.5, "y": 4.0, "width": 3.0, "depth": 3.6}],
  "dry_run": true}}
```

Read the schedules (`rooms` with clear areas, `doors`, `windows`,
`unreachable_rooms`), then repeat with `"dry_run": false`. Continue with
`autocad_draw_structural_grid` (`x_spacings [4.5, 3.0]`, `y_spacings [4.0, 3.6]`,
`unit "m"`, `column_size [0.3, 0.3]`), `autocad_draw_stair_plan`
(`floor_to_floor 3000`, `unit "mm"`), `autocad_draw_sheet` (`paper "A3"`,
`scale 100`), `autocad_check_drawing`, `autocad_quantity_takeoff`
(`wall_height 3000`) and `autocad_save_report` (`report "qc"`,
`path "qc.md"`, `format "md"`). This is the sequence the headless end-to-end
test runs. The MCP prompts `residential_floor_plan`, `drawing_review` and
`sheet_and_plot` walk through these steps.

Sizes are drafting defaults (230/115 mm walls, 900/750 mm doors, 1200 mm
windows; 9"/4.5", 36"/30", 48" in imperial) -- override them for your
project. Stair limits default to rules of thumb (max riser 190 mm, min tread
250 mm, 2R+G 550-700 mm), not any building code; pass your code's limits.

## Troubleshooting

Errors carry a `code` and `recommended_action`; the common ones
(`E_AUTOCAD_NOT_RUNNING`, `E_COM_TIMEOUT`, `E_DOCUMENT_CHANGED`,
`E_OUTPUT_EXISTS`, ...) and recovery after an interrupted job are in
[docs/troubleshooting.md](docs/troubleshooting.md).

## Security and permissions

* Local stdio server; no network listener.
* No tool executes raw AutoCAD commands, AutoLISP or code.
* Deletes default to dry runs; saving over another file needs `overwrite=true`;
  closing with unsaved changes needs `discard_changes=true`.
* Read-only tools never change units or send keystrokes.
* File paths are validated; `AUTOCAD_MCP_ALLOWED_DIRS` confines them.
* The server acts with your user rights on whatever your AutoCAD has open:
  pin the drawing for a job.

See [SECURITY.md](SECURITY.md).

## Limitations

* Live-verified on AutoCAD 2024 only, and only what the 19 live tests assert;
  several COM tools (open/activate drawing, layer properties, stairs, sheets,
  takeoff) are still fake-COM tested only.
* No undo-group or transaction tool yet; use AutoCAD's Undo.
* Doors and windows are drawn over walls, not cut into them; no wall junction
  clean-up.
* Scans, checks and takeoff read top-level model space only (no block
  contents, no paper space).
* Headless backend: DXF only, one drawing at a time.
* Civil 3D, Map 3D, Plant 3D, Electrical and LT features are not implemented.

## Testing

```powershell
pip install pytest
python -m pytest tests -q
```

Live tests need a running AutoCAD (`python -m pytest tests\test_integration_autocad.py -v`).
Layers, recorded results and what was not run: [docs/testing.md](docs/testing.md).

## Development

* [AGENTS.md](AGENTS.md) -- rules for coding agents and contributors.
* [CONTRIBUTING.md](CONTRIBUTING.md) -- workflow, adding a tool, tests.
* Generated files: `python scripts\build_tool_docs.py` (tool reference),
  `python scripts\catalog\build_catalog.py` (capability catalog); tests fail
  when either is stale.

## Versioning and migration

Semantic-ish versions in `src/version.py` (single source; `pyproject.toml`
must match). V0.3.0 keeps every V0.2.x tool name and required argument;
behaviour changes and how to keep old behaviour are listed in
[docs/compatibility.md](docs/compatibility.md#migration-from-v023) and
[CHANGELOG.md](CHANGELOG.md).

## Licence and acknowledgements

This repository does **not** have a licence file yet, so all rights are
reserved by default; choosing one is up to the owner
([docs/analysis/reuse-and-licensing.md](docs/analysis/reuse-and-licensing.md)).

No code from other repositories was copied. Ideas were taken, and
reimplemented, from MIT / Apache-2.0 projects: U-C4N/Autocad-MCP (COM thread
with timeouts, plot handling, path checks, capability refusals),
beiming183-cloud/AutoCAD-MCP (error codes with recovery hints, state
vocabulary, document pinning), LokmenoWer/best-cad-mcp (SDK v2 threading,
annotations), thewisekape/autocad-mcp (QC checks), Psalmustrack/lambdacad-mcp
(verification by measurement), Jjo37/new-acad (bounded summaries). Runtime
dependencies: MCP Python SDK (MIT), pywin32 (PSF), ezdxf (MIT, optional).

## Contributing

Issues and pull requests are welcome; read [CONTRIBUTING.md](CONTRIBUTING.md)
first. Never commit drawings from real projects.

## Documentation

| | |
|---|---|
| [docs/tools.md](docs/tools.md) | every tool with arguments, side effects and backends |
| [docs/feature-catalog.md](docs/feature-catalog.md) | 647 capabilities with status |
| [docs/architecture.md](docs/architecture.md) | how it is built |
| [docs/backends.md](docs/backends.md) | live vs headless |
| [docs/installation.md](docs/installation.md) | install and configuration |
| [docs/client-integrations.md](docs/client-integrations.md) | client setup and what was verified |
| [docs/troubleshooting.md](docs/troubleshooting.md) | errors and recovery |
| [docs/testing.md](docs/testing.md) | test layers and results |
| [docs/compatibility.md](docs/compatibility.md) | versions and migration |
| [docs/analysis/](docs/analysis/) | reference-repository survey and rebuild plan |
