# Changelog

All notable changes to this project. Versions follow `src/version.py`, which
is the only place the version is set (`pyproject.toml` must match; a test
checks it).

## [0.3.0] - unreleased (branch `feat/v0.3.0-rebuild`)

A rebuild for reliability, a second (headless) backend and residential/civil
drafting workflows. All 22 V0.2.x tool names and their required arguments
still work. The 19 live tests pass on AutoCAD 2024 (R24.3); 62 catalogued
capabilities are live-verified, the rest of the COM surface is fake-COM tested.

### Fixed after the first live run (AutoCAD 2024)

* `create_new_drawing` read `Name` / `FullName` right after `Documents.Add`
  without the busy retry and could fail with "Call was rejected by callee"
  (3 of 19 live tests on the first run). Those reads now retry.
* `plot_pdf` reported `layout_settings_restored: false` on fresh drawings:
  their model layout reports an empty paper name, which AutoCAD rejects as
  input. The empty value is no longer written back; it is reported in
  `layout_settings_left_at_device_default`, and any setting that does fail
  is named in `layout_settings_not_restored`.

### Fixed after the headless test campaign (2026-10-17)

A scripted audit of all 64 tools on the headless backend (results under
`test-results/v0.3.0/`) found two gaps where the caller's own mistake reached
the client as `E_INTERNAL` ("report a bug in the server"):

* `autocad_execute_query`: an error in the caller's SELECT (unknown column or
  table, syntax error, wrong number of `?` parameters) is now
  `E_INVALID_INPUT`, and `error.details.tables` lists the tables and columns
  that exist.
* A file-system error that names a path (access denied when exporting onto a
  read-only file, an invalid or over-long file name) is now
  `E_OUTPUT_PATH_REJECTED`. OS errors that name no file (COM start-up
  failures) keep their old mapping.

Eight regression tests were added (`tests/test_db.py`, `tests/test_errors.py`);
six of them fail on the previous code. Not changed: a failed export onto a
read-only file leaves its hidden temporary file in the output folder, and
`autocad_compare_dxf` does not compare rotation, colour, linetype or
lineweight (see `test-results/v0.3.0/*/failures-and-blockers.md`).

### Fixed

* **D1** Tool errors reached clients as the bare text
  `Error executing tool <name>`, because the MCP SDK withholds the message of
  any exception that is not a `ToolError`. Every failure is now a JSON
  envelope with `code`, `message`, `recoverable`, `recommended_action` and
  `details`.
* **D2** Internal release 24.4 was mapped to AutoCAD 2025. The table now
  reads 25.0 = 2025, 25.1 = 2026, 26.0 = 2027 (from reference evidence; only
  2024 has been run on this project's machine).
* **D3** `pyproject.toml` said version 0.2.2 and `mcp>=1.2.0`, which cannot
  import `mcp.server.mcpserver`. Now 0.3.0, `mcp>=2.3,<3`, a declared
  setuptools build backend and an `autocad-mcp` console command.
* **D4** Every tool, read-only ones included, forced Engineering units
  (`LUNITS`, `LUPREC`, `INSUNITS`, `MEASUREMENT`) on the active drawing. The
  units preset is now applied only by tools that change a drawing, only when
  a value differs, and is reported as a `units_changed` notice.
* **D5** ESC was typed into AutoCAD before every tool. It is now sent only by
  tools that change a drawing, and only when `CMDACTIVE` shows a command in
  progress.
* **D6** COM calls had no timeout and ran on whichever worker thread the SDK
  picked. They now run on one dedicated COM thread with a per-call timeout
  (`AUTOCAD_MCP_COM_TIMEOUT`); a timed-out worker is replaced, and the error
  says the call may still complete inside AutoCAD.
* **D7** `count_text_patterns`, `highlight_text_matches` and `execute_query`
  could return unbounded output. They take `limit` (500 / 500 / 1000) and
  report `truncated`.
* **D8** `draw_wall`'s docstring contradicted the units behaviour; tool
  descriptions were rewritten against the units policy.
* **D9** `generate_2d_floor_plan` did not verify what it drew. It now checks
  the entity count, reports `verified`, and supports `dry_run`.

### Added

* **Backends.** `AUTOCAD_MCP_BACKEND=com` (live AutoCAD, default) or `dxf`
  (headless, ezdxf). The backend is fixed for the process; there is no
  automatic fallback. Operations a backend does not implement are refused
  with `E_UNSUPPORTED_BACKEND` and the reason.
* **48 new tools** (70 in total), grouped into 11 toolsets that
  `AUTOCAD_MCP_TOOLSETS` can restrict:
  * core: `autocad_get_capabilities`, `autocad_pin_document`,
    `autocad_unpin_document`, `autocad_list_drawings`, `autocad_open_drawing`,
    `autocad_save_drawing`, `autocad_close_drawing`,
    `autocad_activate_drawing`, `autocad_set_drawing_units`;
  * drawing: `autocad_draw_arc`, `autocad_draw_mtext`;
  * layers: `autocad_list_layers`, `autocad_set_layer_properties`;
  * editing: `autocad_scale_entity`, `autocad_mirror_entity`,
    `autocad_offset_entity`, `autocad_array_rectangular`,
    `autocad_delete_entities` (dry run by default),
    `autocad_set_entity_properties`;
  * query: `autocad_drawing_summary`, `autocad_list_entities`,
    `autocad_get_entity`;
  * annotation: `autocad_add_dimension`, `autocad_add_hatch`;
  * blocks: `autocad_list_blocks`, `autocad_insert_block`,
    `autocad_get_block_attributes`, `autocad_set_block_attributes`;
  * architecture: `autocad_generate_floor_plan` (explicit rooms, doors that
    connect every room, windows, schedules), `autocad_draw_structural_grid`,
    `autocad_design_stair`, `autocad_draw_stair_plan`, `autocad_draw_sheet`;
  * analysis: `autocad_check_drawing`, `autocad_quantity_takeoff`,
    `autocad_save_report`, `autocad_compare_dxf`, `autocad_validate_dxf_file`;
  * output: `autocad_list_layouts`, `autocad_export_dxf`, `autocad_plot_pdf`,
    `autocad_render_preview`;
  * civil: `autocad_civil_alignment_station`, `autocad_civil_station_point`,
    `autocad_civil_ground_profile`, `autocad_civil_surface_volumes`,
    `autocad_civil_pipe_clearance`, `autocad_civil_place_points`.
* **Civil/survey toolset** on both backends: stationing and offsets along a
  LINE or polyline, ground profiles sampled from POINT spot levels,
  grid-method cut/fill volumes between two POINT layers, pipe clearance, and
  numbered COGO point placement with labels. Pure maths in
  `src/domain/civil.py`; no Civil 3D objects, no Civil 3D installation and
  no command execution. Values interpolated beyond the spot levels are
  reported (`extrapolated_nodes`), not hidden.
* **MCP resources** `autocad://capabilities`, `autocad://units`,
  `autocad://layer-standard` and **prompts** `residential_floor_plan`,
  `drawing_review`, `sheet_and_plot`. Server instructions in the initialize
  result.
* **State block** on every result: `accepted`, `preflight`, `executed`,
  `verified` and `saved` are reported separately, with the backend and the
  drawing identity.
* **Document pinning**: a pinned job refuses to act on any other drawing
  (`E_DOCUMENT_CHANGED`) instead of following a tab switch.
* **Units policy**: `AUTOCAD_MCP_UNITS` (`engineering` default, `architectural`,
  `metric_mm`, `metric_m`, `preserve`) and a per-session override through
  `autocad_set_drawing_units`. Drafting defaults (wall, door and window
  sizes) follow the drawing's units.
* **File safety**: output paths are validated (no `..`, UNC, `\\?\` or system
  folders), existing files are never replaced without `overwrite=true`,
  relative paths go to `AUTOCAD_MCP_OUTPUT_DIR`, and
  `AUTOCAD_MCP_ALLOWED_DIRS` confines every file path a tool accepts. Saved files report
  size and SHA-256 read back from disk.
* **Plan engine**: generators build a list of primitives first, then draw it
  on either backend through one emitter and verify the entity count. Every
  generator supports `dry_run`.
* **Tests**: 322 tests -- 302 pass without AutoCAD and 20 live tests skip
  (the 19 pre-civil live tests last passed on AutoCAD 2024; the civil live
  test is added but not yet run), including recorded-fake COM tests, a golden regression that
  proves the V0.2.3 floor plan is reproduced entity-for-entity, headless DXF
  integration tests and real stdio sessions on both backends.
* **Documentation**: reference-repository analysis (`docs/analysis/`), a
  650-entry capability catalog with honest statuses
  (`docs/feature-catalog.md`), generated tool reference (`docs/tools.md`),
  and architecture, backend, installation, client, troubleshooting, testing
  and compatibility guides.

### Changed (behaviour)

| Change | If you relied on the old behaviour |
|---|---|
| Error text is a JSON envelope | parse `error.code` |
| Units preset applied only by drawing-changing tools, only when different | `AUTOCAD_MCP_UNITS=engineering` is still the default for those tools |
| ESC sent only for writes and only when a command is active | none |
| `count_text_patterns`, `highlight_text_matches`, `execute_query` are bounded by `limit` | pass a larger `limit` |
| `draw_wall.thickness` defaults to the standard wall for the drawing's units (9 in inch drawings as before; 230 in mm drawings) | pass `thickness` |
| `generate_2d_floor_plan` draws in the drawing's units and adds `dry_run`, `drawing_unit`, `verified` | identical entities in inch drawings (golden test) |
| `create_new_drawing` gains `pin` and refuses while another drawing is pinned | unpin, or pass `pin=true` |
| Template paths with folders must be existing `.dwt` files | use a bare template name to let AutoCAD search its template path |
| `pyproject.toml` requires `mcp>=2.3,<3` | install into a fresh virtual environment |

Full migration notes: [docs/compatibility.md](docs/compatibility.md#migration-from-v023).

### Security

* No tool executes raw AutoCAD commands, AutoLISP or code. The SQL tool
  (unchanged since V0.2.0) accepts one `SELECT` (or `WITH ... SELECT`)
  statement and runs it on a read-only connection to the scan cache.
* Deletes default to dry runs; closing with unsaved changes needs
  `discard_changes=true`; save-as over another file needs `overwrite=true`.
* Still a local stdio server with no network listener.

### Not verified in this release

* AutoCAD releases other than 2024, and COM tools no live test asserts
  (see the catalog's `tested` entries).
* The `civil` toolset (stationing, ground profiles, volumes, pipe clearance,
  point placement): unit, fake-COM and headless DXF tests only; its live
  test is written but has not been run on AutoCAD.
* Python 3.10-3.13, Linux and macOS (declared or designed for, not run).
* Headless previews (matplotlib not installed on the development machine).
* Codex CLI and Claude Desktop configurations (documented, not run).

## [0.2.3] - 2026-10-16

* Forced the Engineering units preset on the active drawing.
* Added `autocad_generate_2d_floor_plan` (2x3 room grid macro).

## [0.2.2] - 2026-10-16

* Flat `src/` layout; architectural layer tools (`autocad_ensure_layer`,
  `autocad_draw_wall`).
* Fixed an error message that named `create_new_drawing` instead of
  `autocad_create_new_drawing`.

## [0.2.1] - 2026-10-16

* Added `autocad_query_and_highlight`.

## [0.2.0] - 2026-10-16

* Drawing, editing and analysis tools (new drawing, lines, polylines,
  rectangles, circles, text, layers, move/rotate/copy, highlighting, SQLite
  entity scan and read-only queries, text pattern counts).
* Fixed: `CoInitialize` per thread and retry when AutoCAD reports it is busy.

## [0.1.0] - 2026-10-16

* Foundation: `autocad_get_status`, `autocad_launch_application`,
  `autocad_create_test_drawing_with_line`.
