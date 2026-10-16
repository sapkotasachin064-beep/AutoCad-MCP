# Gap analysis: baseline V0.2.3 vs. what the references prove possible

Baseline = commit `3cf9254` on `main`. Every defect below was reproduced or
read in this repository's own code; reference evidence levels follow
[`feature-matrix.md`](feature-matrix.md).

## 1. Defects in the baseline (fix first)

| ID | Severity | Defect | Evidence | Fix (see rebuild plan) |
|---|---|---|---|---|
| D1 | **High** | Every tool error reaches the client as the opaque text `Error executing tool <name>`. MCP SDK 2.3.0 treats any exception other than `ToolError` as a crash and withholds its message. Validation errors, SQL rejections and "AutoCAD is not running" are all lost; the client cannot self-correct. The README claims errors come back "as a structured error". | Probe over real stdio (scratch `probe_errors.py`): `autocad_draw_circle(radius=-1)`, `autocad_execute_query("DELETE ...")`, `autocad_draw_line` with AutoCAD closed all returned only `Error executing tool ...`. SDK source: `mcp/server/mcpserver/exceptions.py` (`UnexpectedToolError`). The existing e2e test only asserts `is_error`, so it passed. | Typed `CadError` hierarchy with stable codes; boundary wrapper raises `ToolError` carrying a JSON envelope (`code`, `message`, `recoverable`, `recommended_action`, `details`) |
| D2 | Medium | Release table maps internal release `24.4` to 2025. AutoCAD 2025 is R25.0, 2026 is R25.1, 2027 is R26.0; there is no 24.4. A 2025+ seat reports `release_year: null`. | `src/utils/constants.py` `RELEASE_TO_YEAR`; references: `autocad-com-mcp` ProgID list (`AutoCAD.Application.25.0  # AutoCAD 2025`, `25.1 # 2026`), `autocad-tarch-mcp` CLAUDE.md (`acad.exe` `R25.0.189.0.0` for 2025), U-C4N live measurement `25.1s (LMS Tech)` = 2026, `MCP_AutocadMap3D` (2027 = R26.0) | Correct table; label 2025-2027 as "from reference evidence, not verified on this machine" |
| D3 | Medium | Packaging: `pyproject.toml` says `version = "0.2.2"` while README/server describe V0.2.3; dependency `mcp>=1.2.0` but the code imports `mcp.server.mcpserver`, which exists only in SDK 2.x -- installing on mcp 1.x fails at import. `[tool.setuptools]` declares no build backend; no console entry point. | `pyproject.toml`; `src/server.py` line 30; installed SDK is 2.3.0 | `mcp>=2.3,<3`, version 0.3.0, optional extras, entry point |
| D4 | **High** | `get_active_document()` forces `LUNITS/LUPREC/INSUNITS/MEASUREMENT` on **every** active document for **every** tool, including read-only ones (`scan_all_entities`, `count_text_patterns`). Pointing a scan at an existing metric drawing silently rewrites its unit settings and marks it modified. `MEASUREMENT` also changes hatch/linetype scaling for the whole drawing. | `src/cad_engine.py` `get_active_document` -> `set_engineering_units` | Explicit units policy (`AUTOCAD_MCP_UNITS`, default keeps V0.2.3's Engineering preset), applied **only** by mutating tools, skipped when values already match, and reported back as `units_changed` |
| D5 | Medium | `clear_pending_command()` types ESC ESC into AutoCAD before every tool, including reads -- it can cancel a command the user is in the middle of. | `src/cad_engine.py` | Read `CMDACTIVE` first; only cancel when a command is actually active; report `pending_command_cancelled` |
| D6 | Medium | No timeout around COM calls. A modal dialog or long regen blocks the tool -- and the AnyIO worker thread -- indefinitely. Concurrent tool calls drive COM concurrently from different threads. | `src/cad_engine.py`, `src/server.py` (sync handlers run on AnyIO worker threads per SDK `func_metadata.py`) | One dedicated COM thread, per-call timeout (`AUTOCAD_MCP_COM_TIMEOUT`), worker replaced after a timeout, timeout error says the call may still land |
| D7 | Medium | Unbounded outputs: `count_text_patterns`, `highlight_text_matches` and `execute_query` return every match/row. A large drawing can produce a response the client cannot hold. | `src/tools/analysis.py`, `src/tools/editing.py`, `src/server.py` | `limit` parameters with `truncated` flags and totals |
| D8 | Low | Stale docstrings: `autocad_draw_wall` says the server "never assumes inches" although V0.2.3 forces inches. | `src/server.py`, `src/tools/architectural.py` | Rewrite against the units policy |
| D9 | Low | `generate_2d_floor_plan` never verifies what it drew (no count check) although its docstring says it verifies the overall result; the floor plan is fixed to a 2x3 grid. | `src/tools/architectural.py` | Count verification; new explicit-room generator |

## 2. Reliability gaps (no defect, missing capability)

| Gap | Why it matters | Reference evidence |
|---|---|---|
| No document pinning: a tool acts on whatever drawing is active when it runs | The user switching drawing tabs mid-job redirects writes | beiming183 leases (V); lambdacad "every reply says which drawing answered" (D) |
| No undo grouping: a 50-entity floor plan is 50+ separate undo steps | User cannot undo one tool call with one Ctrl+Z | U-C4N undo Mark + group (V); lambdacad batch = one undo (D) |
| No machine-readable capability map | Clients cannot tell what this server/backend can do without trying | U-C4N `capabilities()` + typed refusals (V) |
| No output-path policy (template path, save paths) | A tool could be asked to write into system folders or overwrite files | U-C4N `validate_path` (V) |
| No explicit job state reporting | "Request accepted", "executed", "verified", "saved" are conflated in `status: ok` | beiming183 journal states (V) |
| No headless mode | Every test of drawing logic needs live AutoCAD; offline drafting impossible | U-C4N / puran-water ezdxf backends (C) |
| No tool annotations | Clients cannot see which tools are read-only or destructive | best-cad-mcp `ToolAnnotations` (V) |

## 3. Capability gaps by domain

Priority: **P1** = this pass, high value for drafting/civil students and needed
by later features; **P2** = this pass if time allows; **P3** = later.

| Domain (catalog letter) | Baseline | Gap | Priority |
|---|---|---|---|
| E Document lifecycle | create new; save only inside the test tool | open (read-only), save/save-as with overwrite guard, close with unsaved-work guard, list, activate, pin | P1 |
| F Inspection | SQLite scan of 6 entity types | drawing summary (counts, extents, units, layers), entity detail by handle, filtered + paginated listing | P1 |
| G/H Entities and curves | line, 3D polyline, rectangle, circle, text | arc, MTEXT, ellipse, 2D polyline with bulges, points | P1 (arc, MTEXT), P2 (others) |
| G Editing | move, rotate, copy, highlight | delete (dry-run first), scale, mirror, offset, rectangular array, set properties | P1 |
| I Annotation | none | aligned/linear dimensions, leaders, text styles | P1 (dimensions), P2 |
| J Layers / blocks / xrefs | create/ensure layer | list layers, layer state (on/freeze/lock), list blocks, insert block with attributes, read/update attributes; xrefs | P1 layers + blocks, P3 xrefs |
| K Hatch | none | hatch from closed boundary | P1 |
| L Layouts / plotting | none | list layouts, plot layout to PDF with verified output | P1 |
| R/S DXF / DWG | none | DXF export without renaming the document; headless DXF backend | P1 |
| U Evidence | none | file evidence (size, SHA-256), headless PNG preview when matplotlib is present | P1 (hash), P2 (preview) |
| V/W Architecture / residential | wall, fixed-grid floor plan | unit-aware plan engine shared by both backends, plans from explicit room rectangles, room areas, door/window schedule, overall dimensions, dry-run plan | P1 |
| X Structural | none | column grid with bubbles and labels, column marks at intersections | P1 |
| V Stairs | none | stair calculator (riser/tread from user limits; rule-of-thumb check, not a code check) and stair plan | P1 |
| AF Sheets / title blocks | none | sheet border + title block at a scale | P1 |
| Q Validation / QC | none | read-only QC checks with a bounded issue list | P1 |
| AE Quantities | none | lengths/areas/counts per layer from geometry | P1 |
| AI Diff | none | compare two DXF files; scan-based change report | P2 |
| Y/Z Civil 3D / survey | none | surfaces, alignments, profiles, parcels, earthwork | P3 -- Civil 3D is not installed; needs AeccXUiLand COM or a .NET plugin; coordinate/traverse math possible headlessly (P2) |
| AA-AD MEP / P&ID / electrical | none | plumbing/drainage schematics, electrical layouts, P&ID symbols | P3 (catalogued only) |
| N 3D | none | solids | P3 |
| AM Client setup | Claude Code + OpenCode snippets, unverified | verified commands for Claude Code / OpenCode on this machine, documented (untested) Codex / Claude Desktop configs | P1 |

## 4. Blocked or not verifiable here

| Item | Reason |
|---|---|
| Live AutoCAD verification of new COM tools | AutoCAD 2024 is installed but was not running; launching it needs the owner's go-ahead. New COM code is tested against recorded fakes and reported as **not live-verified** until then |
| AutoCAD LT (file IPC) backend | LT not installed |
| Civil 3D / Map 3D | not installed |
| Headless PNG/PDF rendering | `matplotlib`/`Pillow` not installed on this machine; capability reported unavailable rather than installing packages globally unasked |
| Codex CLI integration test | `codex` not installed |
| DWG output from the headless backend | needs the ODA File Converter; not installed |
