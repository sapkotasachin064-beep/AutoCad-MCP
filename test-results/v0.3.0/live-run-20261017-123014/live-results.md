# Live results: AutoCAD MCP v0.3.0 against a real AutoCAD

Run folder: `live-run-20261017-123014`. Every result below was produced by a real AutoCAD, never by fake COM or the headless DXF backend.

**AutoCAD release string (exact):** `24.3s (LMS Tech)` (`Application.Version` and `ACADVER` agree). `_VERNUM` = `U.61.0.0 (UNICODE)`, product `AutoCAD`, `acad.exe` file version `R24.3.61.0.0`, window title `Autodesk AutoCAD 2024`. Windows 11 Pro 10.0.26300, Python 3.14.7, mcp 2.3.0, pywin32 312.

**Totals (final result per case id, 167 cases):** 9 FAIL, 1 NOT_APPLICABLE, 157 PASS. Plus the project's own live test file: 19 passed, 0 failed (`pytest-live-integration.txt`).

## A. The six tools that could not be tested headless

| Tool | Result | Cases (pass / fail) | What it means |
|---|---|---|---|
| `autocad_launch_application` | **FAIL (cold start) / PASS (AutoCAD already running)** | 1 / 1 | Could not start AutoCAD from nothing: AutoCAD crashed itself about 3 seconds after the tool started it (AutoCAD's own .NET start-up error), and the tool said so honestly after 89 s. Started by hand, AutoCAD ran fine; calling the tool then only checks it and touches nothing. One attempt, not retried. |
| `autocad_create_test_drawing_with_line` | **FAIL** | 1 / 3 | Draws the line at (0,0)-(100,100), saves a real DWG and the file matches. But 2 of 13 calls failed with an internal error after the file was already saved, and it writes to any folder, ignoring the allowed-folder setting. |
| `autocad_highlight_entity` | **FAIL** | 8 / 2 | Argument checks, colour change and read-back work. The 'temporary' highlight is not visible on AutoCAD's screen (the tool's own redraw wipes it), and a 'persistent' colour is stored but only shows after the next redraw. |
| `autocad_highlight_text_matches` | **FAIL** | 9 / 1 | Finds exactly the right TEXT/MTEXT, never changes the text, limit/regex/clear handled. The highlight itself is not visible on screen (same cause as highlight_entity). |
| `autocad_query_and_highlight` | **FAIL** | 9 / 1 | Query rules, stale handles and error codes work. The highlight is not visible on screen, and rows from another drawing's scan can recolour unrelated entities in the active drawing. |
| `autocad_plot_pdf` | **PASS** | 15 / 0 | Real one-page PDFs from model space and a layout, correct page size for the chosen paper, plot style applied, refusals clean, AutoCAD's plot settings restored (one low-severity note about an unset paper name). |

None of the six stayed BLOCKED. The cold-start half of `autocad_launch_application` is the only part that could not be verified (AutoCAD crashed on its own).

## B. Also requested

| Area | Result | Cases (pass / fail) | Tools |
|---|---|---|---|
| Open / activate / pin / save / close (two scratch drawings) | **PASS** | 34 / 0 | `autocad_create_new_drawing`, `autocad_list_drawings`, `autocad_open_drawing`, `autocad_activate_drawing`, `autocad_pin_document`, `autocad_unpin_document`, `autocad_save_drawing`, `autocad_close_drawing` |
| Layer property changes | **PASS** | 20 / 0 | `autocad_set_layer_properties`, `autocad_create_layer`, `autocad_list_layers` |
| Stair | **PASS** | 7 / 0 | `autocad_design_stair`, `autocad_draw_stair_plan` |
| Sheet and title block | **PASS** | 6 / 0 | `autocad_draw_sheet` |
| Takeoff, checks and saved reports | **FAIL** | 17 / 1 | `autocad_quantity_takeoff`, `autocad_check_drawing`, `autocad_save_report`, `autocad_scan_all_entities` |
| Layouts and DXF export | **PASS** | 5 / 0 | `autocad_list_layouts`, `autocad_export_dxf` |
| COM timeout path | **PASS** | 6 / 0 | `autocad_get_capabilities` |
| Status | **PASS** | 6 / 0 | `autocad_get_status` |

## C. Failed or unverified, with the evidence

| Case | Tool | Status | Why (evidence) |
|---|---|---|---|
| LV10 | `autocad_launch_application` | FAIL | check failed: {"installed": true, "running": false, "connected": false, "supported": false, "version": null, "release_year": null, "message": "Failed to launch AutoCAD via COM: (-2146959355, 'Server execution failed', None, None)", "backend": "com", "verified": false, "state": {"accepted": true, "preflight_passed... |
| TD02 | `autocad_create_test_drawing_with_line` | FAIL | call failed: {"ok": false, "error": {"code": "E_INTERNAL", "message": "AttributeError: AddLine.Handle", "recoverable": false, "recommended_action": "report_a_bug_with_the_server_log"}, "tool": "autocad_create_test_drawing_with_line", "backend": "com"} |
| TD03 | `autocad_create_test_drawing_with_line` | FAIL | output_dir outside AUTOCAD_MCP_ALLOWED_DIRS (C:\Users\This PC\Desktop\Autocad Mcp Server\.claude\worktrees\elated-austin-a13117\test-results\v0.3.0\live-run-20261017-123014\workspace) was not rejected: result {"status": "ok", "file_path": "C:\\Users\\This PC\\Desktop\\Autocad Mcp Server\\.claude\\worktrees\\elated-austin-a13117\\test-results\\v0.3.0\\live-run-20261017-123014\\outside_sandbox\\test-drawings\\mcp_test_20261017_...; files created there: ['C:\\Users\\This PC\\Desktop\\Autocad Mcp Server\\.claude\\worktrees\\elated-austin-a13117\\test-results\\v0.3.0\\live-run-20261017-123014\\outside_sandbox\\test-drawings\\mcp_test_20261017_124942_342114.dwg'] |
| TD04 | `autocad_create_test_drawing_with_line` | FAIL | 1 of 10 calls failed (['E_INTERNAL']): AttributeError: AddLine.Handle; 1 of the failed calls had already saved a DWG and left the drawing open |
| HL02 | `autocad_highlight_entity` | FAIL | the tool reported success but nothing is highlighted on AutoCAD's screen: +0 blue px after the call (a direct Highlight(True) gives +2873; Highlight(True) followed by doc.Regen(1) -- the tool's own sequence -- gives +0) |
| HL02b | `autocad_highlight_entity` | FAIL | after the persistent highlight call, +0 red pixels appeared on AutoCAD's screen without any redraw by the harness; after a regen by the harness +444 red pixels (the colour IS stored, it is only repainted on the next redraw) |
| HL19 | `autocad_highlight_text_matches` | FAIL | the tool reported success but nothing is highlighted on AutoCAD's screen: +0 blue px after the call (a direct Highlight(True) gives +2873; Highlight(True) followed by doc.Regen(1) -- the tool's own sequence -- gives +0) |
| HL29 | `autocad_query_and_highlight` | FAIL | the tool reported success but nothing is highlighted on AutoCAD's screen: +0 blue px after the call (a direct Highlight(True) gives +2873; Highlight(True) followed by doc.Regen(1) -- the tool's own sequence -- gives +0) |
| RP08 | `autocad_save_report` | FAIL | autocad_save_report answered 'E_INTERNAL' ('ToolError: {"ok": false, "error": {"code": "E_NO_ACTIVE_DOCUMENT", "message": "No document is open in AutoCAD. Call autocad_create_new_drawing or open a drawing first.", "recoverable": true, "recommen') although the wrapped tool's own typed error is E_NO_ACTIVE_DOCUMENT; a client is told to 'report a bug' (recommended_action='report_a_bug_with_the_server_log', recoverable=False) |

## D. Every final case

| Case | Tool / area | Title | Status | Method | Raw log |
|---|---|---|---|---|---|
| LV01 | `autocad_get_status` | status while AutoCAD is closed: installed, not running, not connected (and the call does not start it) | PASS | real-MCP-stdio+direct-COM | `01_launch.jsonl#2` |
| LV02 | `autocad_list_drawings` | a drawing tool while AutoCAD is closed fails with E_AUTOCAD_NOT_RUNNING and does not start AutoCAD | PASS | real-MCP-stdio+direct-COM | `01_launch.jsonl#3` |
| LV10 | `autocad_launch_application` | start AutoCAD 2024 from cold through the tool and wait until COM answers | FAIL | real-MCP-stdio+direct-COM | `01_launch.jsonl#4` |
| LV20 | `autocad_get_status` | status with AutoCAD running: connected, supported, release 2024, version equals the direct COM Application.Version | PASS | real-MCP-stdio+direct-COM | `01b_attach.jsonl#2` |
| LV21 | `autocad_launch_application` | launch while AutoCAD already runs: only verifies it (same process, drawings untouched) | PASS | real-MCP-stdio+direct-COM | `01b_attach.jsonl#3` |
| LV22 | `autocad_get_capabilities` | capabilities on the live backend: 64 tools, 6 com-only, 120 s COM timeout | PASS | real-MCP-stdio | `01b_attach.jsonl#4` |
| LV23 | `autocad_list_drawings` | list_drawings matches the drawings AutoCAD itself reports (direct COM) | PASS | real-MCP-stdio+direct-COM | `01b_attach.jsonl#5` |
| PT-test_create_new_drawing_becomes_active | `` | project live test test_create_new_drawing_becomes_active | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_draw_line_creates_real_entity | `` | project live test test_draw_line_creates_real_entity | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_draw_circle_and_create_layer | `` | project live test test_draw_circle_and_create_layer | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_draw_rectangle_and_polyline | `` | project live test test_draw_rectangle_and_polyline | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_draw_text | `` | project live test test_draw_text | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_move_rotate_copy_entity | `` | project live test test_move_rotate_copy_entity | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_highlight_entity_temporary_preserves_color | `` | project live test test_highlight_entity_temporary_preserves_color | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_highlight_entity_persistent_changes_color | `` | project live test test_highlight_entity_persistent_changes_color | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_highlight_text_matches_does_not_modify_text | `` | project live test test_highlight_text_matches_does_not_modify_text | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_count_text_patterns_literal_and_regex | `` | project live test test_count_text_patterns_literal_and_regex | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_scan_all_entities_and_execute_query_round_trip | `` | project live test test_scan_all_entities_and_execute_query_round_trip | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_v030_list_drawings_and_units | `` | project live test test_v030_list_drawings_and_units | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_v030_summary_list_and_detail | `` | project live test test_v030_summary_list_and_detail | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_v030_modify_suite | `` | project live test test_v030_modify_suite | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_v030_annotation_live | `` | project live test test_v030_annotation_live | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_v030_blocks_live | `` | project live test test_v030_blocks_live | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_v030_export_and_plot_live | `` | project live test test_v030_export_and_plot_live | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_v030_save_as_then_close | `` | project live test test_v030_save_as_then_close | PASS | pytest | `pytest-live-integration.txt` |
| PT-test_v030_generators_live | `` | project live test test_v030_generators_live | PASS | pytest | `pytest-live-integration.txt` |
| PTF-1 | `autocad_plot_pdf` | PDF written by the project's live plot test is a real PDF (header, size, %%EOF) | PASS | pytest+file | `` |
| PTF-2 | `autocad_export_dxf` | DXF written by the project's live export test is readable by ezdxf | PASS | pytest+file | `` |
| PTF-3 | `autocad_save_drawing` | DWG written by the project's live save-as test has a DWG header | PASS | pytest+file | `` |
| DOC01 | `autocad_list_drawings` | no drawing open at the start: tool and direct COM agree | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#2` |
| DOC02 | `autocad_create_new_drawing` | create scratch drawing 1: becomes the active, unsaved drawing (direct COM agrees) | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#3` |
| DOC03 | `autocad_pin_document` | pin the session to drawing 1 | PASS | real-MCP-stdio | `03_documents.jsonl#4` |
| DOC04 | `autocad_create_new_drawing` | creating a drawing while pinned is refused (E_DOCUMENT_PINNED) and adds nothing | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#5` |
| DOC05 | `autocad_create_new_drawing` | pin=true creates scratch drawing 2 and moves the pin to it | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#6` |
| DOC06 | `autocad_list_drawings` | list shows both drawings, drawing 2 active and pinned (direct COM agrees) | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#7` |
| DOC07 | `autocad_activate_drawing` | activating another drawing while pinned is refused and nothing switches | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#9` |
| DOC08 | `autocad_activate_drawing` | activate drawing 1 with pin=true: switches in AutoCAD and moves the pin | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#10` |
| DOC09 | `autocad_pin_document` | user switches drawing tab while pinned: every tool refuses with E_DOCUMENT_CHANGED, nothing is drawn in the wrong drawing, work resumes after returning | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#13` |
| DOC10 | `autocad_unpin_document` | unpin releases the pin | PASS | real-MCP-stdio | `03_documents.jsonl#14` |
| DOC11 | `autocad_activate_drawing` | unknown identity -> E_DOCUMENT_NOT_FOUND listing the open drawings | PASS | real-MCP-stdio | `03_documents.jsonl#15` |
| DOC12 | `autocad_save_drawing` | save drawing 1 as live_s1.dwg (R2018): DWG header AC1032, size and SHA-256 re-read from disk, identity becomes the path | PASS | real-MCP-stdio+direct-COM+file | `03_documents.jsonl#17` |
| DOC13 | `autocad_save_drawing` | save drawing 2 as live_s2.dwg with version R2010: header AC1024 | PASS | real-MCP-stdio+file | `03_documents.jsonl#19` |
| DOC14 | `autocad_save_drawing` | save-as onto another existing file is refused (E_OUTPUT_EXISTS), file untouched, drawing keeps its name | PASS | real-MCP-stdio+direct-COM+file | `03_documents.jsonl#20` |
| DOC15 | `autocad_save_drawing` | plain Save (no path) of the changed drawing 2 rewrites its own file | PASS | real-MCP-stdio+file | `03_documents.jsonl#22` |
| DOC16 | `autocad_close_drawing` | closing a drawing with unsaved changes is refused (E_UNSAVED_CHANGES), drawing stays open | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#25` |
| DOC17 | `autocad_close_drawing` | close with discard_changes=true: closed in AutoCAD (direct COM), changes thrown away | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#26` |
| DOC18 | `autocad_open_drawing` | re-open live_s1.dwg (read-only by default): read-only in AutoCAD, content is exactly what was saved (the discarded circle is absent) | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#27` |
| DOC19 | `autocad_save_drawing` | plain Save on a read-only drawing is refused with E_INVALID_INPUT | PASS | real-MCP-stdio | `03_documents.jsonl#28` |
| DOC20 | `autocad_open_drawing` | opening an already-open file only activates it (no second window) | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#29` |
| DOC21 | `autocad_open_drawing` | open live_s2.dwg editable (read_only=false): content is the saved line + circle | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#31` |
| DOC22 | `autocad_save_drawing` | plain Save on the re-opened editable drawing works and changes the file | PASS | real-MCP-stdio+file | `03_documents.jsonl#33` |
| DOC23 | `autocad_open_drawing` | opening a missing file gives a typed error and opens nothing | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#34` |
| DOC24 | `autocad_open_drawing` | opening a path outside the allowed folder is refused before AutoCAD is asked | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#35` |
| DOC25 | `autocad_open_drawing` | a .txt path is refused (E_INVALID_INPUT) | PASS | real-MCP-stdio | `03_documents.jsonl#36` |
| DOC26 | `autocad_export_dxf` | export a DXF copy of the active drawing; the open drawing keeps its name | PASS | real-MCP-stdio+file | `03_documents.jsonl#37` |
| DOC27 | `autocad_open_drawing` | open the exported DXF (read-only): AutoCAD shows the same line, circle and text | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#38` |
| TD01 | `autocad_create_test_drawing_with_line` | create_test_drawing_with_line: DWG saved under output_dir, one line (0,0,0)-(100,100,0) with the reported handle (direct COM), file is a DWG | PASS | real-MCP-stdio+direct-COM+file | `03_documents.jsonl#39` |
| TD02 | `autocad_create_test_drawing_with_line` | without output_dir the file goes to AUTOCAD_MCP_OUTPUT_DIR | FAIL | real-MCP-stdio+file | `03_documents.jsonl#40` |
| TD03 | `autocad_create_test_drawing_with_line` | output_dir outside AUTOCAD_MCP_ALLOWED_DIRS must be rejected (AGENTS.md invariant 8: never write outside the allowed folders) | FAIL | real-MCP-stdio+file | `03_documents.jsonl#41` |
| DOC30 | `autocad_list_drawings` | final listing agrees with AutoCAD (direct COM) | PASS | real-MCP-stdio+direct-COM | `03_documents.jsonl#42` |
| LAY01 | `autocad_create_layer` | create the test layer (colour 3); direct COM shows it with default flags | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#3` |
| LAY02 | `autocad_set_layer_properties` | switch the layer off (on=false): only that flag changes, direct COM agrees | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#4` |
| LAY03 | `autocad_set_layer_properties` | freeze it (frozen=true): only that flag changes | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#5` |
| LAY04 | `autocad_set_layer_properties` | lock it (locked=true): only that flag changes | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#6` |
| LAY05 | `autocad_set_layer_properties` | colour 5: only the colour changes | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#7` |
| LAY06 | `autocad_set_layer_properties` | linetype DASHED: loaded from the AutoCAD library when missing (was NOT loaded before) and assigned | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#8` |
| LAY07 | `autocad_set_layer_properties` | lineweight 35 (0.35 mm): only the lineweight changes | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#9` |
| LAY08 | `autocad_set_layer_properties` | plottable=false: only that flag changes | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#10` |
| LAY09 | `autocad_set_layer_properties` | all seven properties in one call restore the defaults (on, thawed, unlocked, colour 1, Continuous, default weight, plottable) | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#11` |
| LAY10 | `autocad_set_layer_properties` | layer names are case-insensitive (lower-case spelling works) | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#12` |
| LAY11 | `autocad_set_layer_properties` | switch it back on | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#13` |
| LAY12 | `autocad_set_layer_properties` | freezing the current layer (0) is refused up front (E_INVALID_INPUT), layer stays thawed | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#14` |
| LAY13 | `autocad_set_layer_properties` | unknown layer -> E_LAYER_NOT_FOUND and nothing is created | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#15` |
| LAY14 | `autocad_set_layer_properties` | no property given -> E_INVALID_INPUT | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#16` |
| LAY15 | `autocad_set_layer_properties` | lineweight 37 is not an AutoCAD lineweight -> E_INVALID_INPUT, layer untouched | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#17` |
| LAY16 | `autocad_set_layer_properties` | colour 300 -> E_INVALID_INPUT, layer untouched | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#18` |
| LAY17 | `autocad_set_layer_properties` | a linetype that is in no library -> E_INVALID_INPUT, layer untouched | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#19` |
| LAY18 | `autocad_set_layer_properties` | a linetype name with illegal characters is rejected before any COM call | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#20` |
| LAY19 | `autocad_list_layers` | list_layers equals AutoCAD's own layer table for every layer and every flag (direct COM) | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#21` |
| LAY20 | `autocad_set_layer_properties` | an entity on a frozen layer stays in the drawing and in list_entities; thawing restores the layer | PASS | real-MCP-stdio+direct-COM | `04_layers.jsonl#25` |
| TD04 | `autocad_create_test_drawing_with_line` | 10 consecutive calls all succeed (TD02 failed once with an internal AttributeError) | FAIL | real-MCP-stdio+direct-COM | `04b_testdrawing_repeat.jsonl#1-11` |
| HL01 | `autocad_highlight_entity` | temporary highlight: accepted, colour untouched (direct COM), and honestly reports verified=false (state is not readable over COM) | PASS | real-MCP-stdio+direct-COM | `05_highlight.jsonl#11` |
| HL03 | `autocad_highlight_entity` | clear=true switches the temporary highlight off | PASS | real-MCP-stdio+direct-COM | `05_highlight.jsonl#12` |
| HL04 | `autocad_highlight_entity` | persistent highlight sets the colour (read back: 1) and reports the original (256) | PASS | real-MCP-stdio+direct-COM | `05_highlight.jsonl#13` |
| HL02 | `autocad_highlight_entity` | temporary highlight is visible on AutoCAD's screen and clear=true removes it (pictures, final) | FAIL | real-MCP-stdio+direct-COM+window-capture | `05d_highlight_visual_all.jsonl#14` |
| HL05 | `autocad_highlight_entity` | persistent highlight colour 4 on another line | PASS | real-MCP-stdio+direct-COM | `05_highlight.jsonl#14` |
| HL06 | `autocad_highlight_entity` | a well-formed but non-existent handle -> E_ENTITY_NOT_FOUND | PASS | real-MCP-stdio | `05_highlight.jsonl#15` |
| HL07 | `autocad_highlight_entity` | a malformed handle -> E_INVALID_INPUT | PASS | real-MCP-stdio | `05_highlight.jsonl#16` |
| HL08 | `autocad_highlight_entity` | unknown method -> E_INVALID_INPUT | PASS | real-MCP-stdio | `05_highlight.jsonl#17` |
| HL09 | `autocad_highlight_entity` | persistent colour 999 -> E_INVALID_INPUT and the entity keeps its colour | PASS | real-MCP-stdio+direct-COM | `05_highlight.jsonl#18` |
| HL10 | `autocad_highlight_text_matches` | literal 'PMC-3M': exactly the 3 TEXT + 1 MTEXT entities, text content unchanged, colours untouched (direct COM) | PASS | real-MCP-stdio+direct-COM | `05_highlight.jsonl#19` |
| HL11 | `autocad_highlight_text_matches` | regex PMC-3M-A\d+ matches the 2 TEXT + the MTEXT, not PMC-3M-B7 | PASS | real-MCP-stdio | `05_highlight.jsonl#20` |
| HL12 | `autocad_highlight_text_matches` | limit=2: match_count stays 4, only 2 listed, truncated=true | PASS | real-MCP-stdio | `05_highlight.jsonl#21` |
| HL13 | `autocad_highlight_text_matches` | clear=true reports highlighted=false for every match | PASS | real-MCP-stdio | `05_highlight.jsonl#22` |
| HL14 | `autocad_highlight_text_matches` | persistent colour 2 on 'PMC-3M-A': 3 matches recoloured (direct COM), others and all text content untouched | PASS | real-MCP-stdio+direct-COM | `05_highlight.jsonl#23` |
| HL15 | `autocad_highlight_text_matches` | empty literal pattern -> E_INVALID_INPUT | PASS | real-MCP-stdio | `05_highlight.jsonl#24` |
| HL16 | `autocad_highlight_text_matches` | invalid regex -> E_INVALID_INPUT | PASS | real-MCP-stdio | `05_highlight.jsonl#25` |
| HL17 | `autocad_highlight_text_matches` | no match -> ok with match_count 0 | PASS | real-MCP-stdio | `05_highlight.jsonl#26` |
| HL18 | `autocad_highlight_text_matches` | matching is case-sensitive (lower-case pattern finds nothing) | PASS | real-MCP-stdio | `05_highlight.jsonl#27` |
| HL20 | `autocad_scan_all_entities` | scan: 8 entities counted by type like AutoCAD does, and the SQLite file (read independently) holds exactly those handles | PASS | real-MCP-stdio+direct-COM+file | `05_highlight.jsonl#28` |
| HL21 | `autocad_query_and_highlight` | query for lines, temporary highlight: both line handles highlighted, none missing, colours untouched | PASS | real-MCP-stdio+direct-COM | `05_highlight.jsonl#29` |
| HL22 | `autocad_query_and_highlight` | query on layer MCP_H, persistent colour 6: only the circle changes (direct COM) | PASS | real-MCP-stdio+direct-COM | `05_highlight.jsonl#30` |
| HL23 | `autocad_query_and_highlight` | a stale handle (entity deleted after the scan) is reported in not_found, the rest is highlighted, nothing is raised | PASS | real-MCP-stdio | `05_highlight.jsonl#32` |
| HL24 | `autocad_query_and_highlight` | a query without a handle column -> E_INVALID_INPUT | PASS | real-MCP-stdio | `05_highlight.jsonl#33` |
| HL25 | `autocad_query_and_highlight` | a write statement is rejected (E_QUERY_REJECTED) | PASS | real-MCP-stdio | `05_highlight.jsonl#34` |
| HL26 | `autocad_query_and_highlight` | two statements are rejected (E_QUERY_REJECTED) | PASS | real-MCP-stdio | `05_highlight.jsonl#35` |
| HL27 | `autocad_query_and_highlight` | a query with no rows highlights nothing and says so | PASS | real-MCP-stdio | `05_highlight.jsonl#36` |
| HL28 | `autocad_query_and_highlight` | clear=true with a query highlights none visually but reports the handles processed | PASS | real-MCP-stdio | `05_highlight.jsonl#37` |
| HL30 | `autocad_query_and_highlight` | observation: scan rows of drawing A used while drawing B is active (handle collision between drawings) | PASS | real-MCP-stdio+direct-COM | `05_highlight.jsonl#42` |
| HL02b | `autocad_highlight_entity` | persistent highlight colour is visible on AutoCAD's screen right after the call (red pixels appear) | FAIL | real-MCP-stdio+direct-COM+window-capture | `05d_highlight_visual_all.jsonl#14` |
| HL19 | `autocad_highlight_text_matches` | temporary text highlight is visible on AutoCAD's screen and clear removes it (pictures) | FAIL | real-MCP-stdio+direct-COM+window-capture | `05d_highlight_visual_all.jsonl#14` |
| HL29 | `autocad_query_and_highlight` | temporary query highlight is visible on AutoCAD's screen and clear removes it (pictures) | FAIL | real-MCP-stdio+direct-COM+window-capture | `05d_highlight_visual_all.jsonl#14` |
| PL00 | `autocad_list_layouts` | list_layouts: Model + paper-space layouts, device / paper / style / plot type equal AutoCAD's own values (direct COM) | PASS | real-MCP-stdio+direct-COM | `06_plot.jsonl#9` |
| PL01 | `autocad_plot_pdf` | plot model space: a real 1-page PDF (header, %%EOF, size), page size = reported paper_mm, drawing content and the red layer present, layout settings / BACKGROUNDPLOT / active layout restored (direct COM) | PASS | real-MCP-stdio+direct-COM+file | `06_plot.jsonl#10` |
| PL02 | `autocad_plot_pdf` | plotting onto an existing file is refused (E_OUTPUT_EXISTS), the file is untouched | PASS | real-MCP-stdio+file | `06_plot.jsonl#11` |
| PL03 | `autocad_plot_pdf` | overwrite=true replaces it with a valid PDF and leaves no temporary file | PASS | real-MCP-stdio+file | `06_plot.jsonl#12` |
| PL04 | `autocad_plot_pdf` | paper: an ambiguous name is refused with the candidate list; a listed A3 name produces an A3-sized PDF (page size read from the PDF) | PASS | real-MCP-stdio+direct-COM+file | `06_plot.jsonl#15` |
| PL05 | `autocad_plot_pdf` | unknown layout -> E_LAYOUT_NOT_FOUND listing the layouts, no file | PASS | real-MCP-stdio+file | `06_plot.jsonl#16` |
| PL06 | `autocad_plot_pdf` | plot the paper-space layout 'Layout1': valid PDF, page size equals reported paper_mm, settings restored | PASS | real-MCP-stdio+direct-COM+file | `06_plot.jsonl#17` |
| PL07 | `autocad_plot_pdf` | plot_style monochrome.ctb: the PDF has no red strokes any more (PL01 had), and the layout's style is restored | PASS | real-MCP-stdio+direct-COM+file | `06_plot.jsonl#18` |
| PL08 | `autocad_plot_pdf` | an unknown plot style fails cleanly: no PDF, no temp file, every setting restored | PASS | real-MCP-stdio+direct-COM+file | `06_plot.jsonl#19` |
| PL09 | `autocad_plot_pdf` | a relative path is resolved against the output folder | PASS | real-MCP-stdio+file | `06_plot.jsonl#20` |
| PL10 | `autocad_plot_pdf` | a .txt target is refused (E_INVALID_INPUT) | PASS | real-MCP-stdio | `06_plot.jsonl#21` |
| PL11 | `autocad_plot_pdf` | a target outside the allowed folder is refused (E_OUTPUT_PATH_REJECTED), nothing written | PASS | real-MCP-stdio+file | `06_plot.jsonl#22` |
| PL12 | `autocad_plot_pdf` | a path with '..' is refused (E_OUTPUT_PATH_REJECTED) | PASS | real-MCP-stdio | `06_plot.jsonl#23` |
| PL13 | `autocad_plot_pdf` | a missing folder gives E_FILE_NOT_FOUND | PASS | real-MCP-stdio | `06_plot.jsonl#24` |
| PL14 | `autocad_export_dxf` | export_dxf: the file re-read with ezdxf holds the circle, line, 3D polyline and text and the MCP_RED layer; SHA-256 matches | PASS | real-MCP-stdio+file | `06_plot.jsonl#25` |
| PL15 | `autocad_export_dxf` | exporting onto an existing file is refused (E_OUTPUT_EXISTS) | PASS | real-MCP-stdio | `06_plot.jsonl#26` |
| ST01 | `autocad_design_stair` | stair for 3000 mm on the live backend: 16 risers of 187.5, 15 treads of 250, 3750 run, 2R+G and pitch re-derived here; labelled as rule-of-thumb, not a code | PASS | real-MCP-stdio | `07_architecture.jsonl#2` |
| ST02 | `autocad_design_stair` | zero rise rejected | PASS | real-MCP-stdio | `07_architecture.jsonl#3` |
| ST03 | `autocad_draw_stair_plan` | stair plan dry run: 18 entities announced, nothing drawn (direct COM count unchanged) | PASS | real-MCP-stdio+direct-COM | `07_architecture.jsonl#6` |
| ST04 | `autocad_draw_stair_plan` | draw the stair plan: all 18 entities read back from AutoCAD one by one equal the announced plan (geometry, layer, text, height); layers and colours exist | PASS | real-MCP-stdio+direct-COM | `07_architecture.jsonl#7` |
| ST05 | `autocad_draw_stair_plan` | stair geometry checked against numbers derived by hand (tread spacing, width, run, note) | PASS | real-MCP-stdio+direct-COM | `07_architecture.jsonl#7` |
| ST06 | `autocad_draw_stair_plan` | direction 0 climbs along +X: footprint 3750 x 900 mm (AutoCAD bounding box) | PASS | real-MCP-stdio+direct-COM | `07_architecture.jsonl#8` |
| ST07 | `autocad_draw_stair_plan` | a 45-degree direction is refused and nothing is drawn | PASS | real-MCP-stdio+direct-COM | `07_architecture.jsonl#9` |
| SH01 | `autocad_draw_sheet` | A3 sheet at 1:100, dry run: 20 entities, 420 x 297 mm, usable area (-1000,-7000)..(38000,20700) as derived by hand; nothing drawn | PASS | real-MCP-stdio+direct-COM | `07_architecture.jsonl#10` |
| SH02 | `autocad_draw_sheet` | draw the A3 sheet: all 20 entities read back from AutoCAD equal the plan; edge is 42000 x 29700 from the chosen origin; label / value text heights are 250 / 350 (paper 2.5 / 3.5 mm x 100) | PASS | real-MCP-stdio+direct-COM | `07_architecture.jsonl#11` |
| SH03 | `autocad_draw_sheet` | unknown paper size rejected and nothing is drawn | PASS | real-MCP-stdio+direct-COM | `07_architecture.jsonl#12` |
| SH04 | `autocad_draw_sheet` | zero scale rejected and nothing is drawn | PASS | real-MCP-stdio+direct-COM | `07_architecture.jsonl#13` |
| SH05 | `autocad_draw_sheet` | an unknown title-block field is rejected and nothing is drawn | PASS | real-MCP-stdio+direct-COM | `07_architecture.jsonl#14` |
| SH06 | `autocad_draw_sheet` | unknown orientation rejected and nothing is drawn | PASS | real-MCP-stdio+direct-COM | `07_architecture.jsonl#15` |
| TK01 | `autocad_quantity_takeoff` | takeoff on a drawing built from known numbers: wall length 8000, wall area 1.84e6, face area 21.6e6, volume 4.968e9, room 12 m2, circle pi*500^2, lines 3000 + 7000, arc pi/2*1000, hatch 12 m2, 2 blocks, 2 texts - every figure computed here from the coordinates | PASS | real-MCP-stdio+hand-computed | `07b_takeoff.jsonl#17` |
| TK02 | `autocad_quantity_takeoff` | layer filter (case-insensitive) keeps only ROOM | PASS | real-MCP-stdio | `07b_takeoff.jsonl#18` |
| TK03 | `autocad_quantity_takeoff` | a negative wall height is rejected | PASS | real-MCP-stdio | `07b_takeoff.jsonl#19` |
| TK04 | `autocad_quantity_takeoff` | max_entities=5 truncates and says so | PASS | real-MCP-stdio | `07b_takeoff.jsonl#20` |
| RP01 | `autocad_save_report` | save the takeoff as json: file exists, size and SHA-256 equal a fresh hash, content has the layers | PASS | real-MCP-stdio+file | `07b_takeoff.jsonl#21` |
| RP02 | `autocad_save_report` | save the takeoff as csv: file exists, size and SHA-256 equal a fresh hash, content has the layers | PASS | real-MCP-stdio+file | `07b_takeoff.jsonl#22` |
| RP03 | `autocad_save_report` | save the takeoff as md: file exists, size and SHA-256 equal a fresh hash, content has the layers | PASS | real-MCP-stdio+file | `07b_takeoff.jsonl#23` |
| RP04 | `autocad_save_report` | an existing report is not overwritten (E_OUTPUT_EXISTS) | PASS | real-MCP-stdio | `07b_takeoff.jsonl#24` |
| RP05 | `autocad_save_report` | an unknown report kind is rejected | PASS | real-MCP-stdio | `07b_takeoff.jsonl#25` |
| RP06 | `autocad_save_report` | an unknown format is rejected | PASS | real-MCP-stdio | `07b_takeoff.jsonl#26` |
| QC01 | `autocad_check_drawing` | check_drawing on the live drawing finds exactly the 3 planted issues (a duplicate line, a line on layer 0, an open A-WALL polyline) by handle | PASS | real-MCP-stdio+direct-COM | `07b_takeoff.jsonl#30` |
| QC02 | `autocad_check_drawing` | an unknown rule is rejected | PASS | real-MCP-stdio | `07b_takeoff.jsonl#31` |
| QC03 | `autocad_check_drawing` | layer-name rule flags the non-standard layer names (ROOM, COL, LINES, ...) | PASS | real-MCP-stdio | `07b_takeoff.jsonl#32` |
| RP07 | `autocad_save_report` | save the QC report as json: SHA-256 equals a fresh hash, content has the issues | PASS | real-MCP-stdio+file | `07b_takeoff.jsonl#33` |
| TK00 | `` | active drawing switched away from the scratch drawing by someone other than the server while the takeoff cases ran | NOT_APPLICABLE | direct-COM | `07b_interference.json` |
| TO00 | `autocad_get_capabilities` | server runs with AUTOCAD_MCP_COM_TIMEOUT=1.0 and a fresh COM worker | PASS | real-MCP-stdio | `08_timeout.jsonl#2` |
| TO01 | `autocad_create_new_drawing` | a real AutoCAD call slower than the limit returns E_COM_TIMEOUT near 1 s (worker_replaced=true, advice: inspect before retrying) | PASS | real-MCP-stdio | `08_timeout.jsonl#3` |
| TO02 | `autocad_create_new_drawing` | the timed-out call still completes in AutoCAD (E_COM_TIMEOUT's warning is true: exactly one new drawing appears) | PASS | real-MCP-stdio+direct-COM | `08_timeout.jsonl#3` |
| TO03 | `autocad_list_drawings` | after the timeout a fresh worker serves the next call normally (list_drawings equals AutoCAD's own list) | PASS | real-MCP-stdio+direct-COM | `08_timeout.jsonl#4` |
| TO04 | `autocad_get_capabilities` | com_worker statistics show exactly one abandoned worker and generation 2 (the replacement), idle | PASS | real-MCP-stdio | `08_timeout.jsonl#5` |
| TO05 | `autocad_list_drawings` | two concurrent calls: the one stuck behind the slow call is refused with E_COM_BUSY (it never started), not left hanging | PASS | real-MCP-stdio+direct-COM | `08_timeout.jsonl#7` |
| ENV01 | `` | src/ and tests/ are byte-identical before and after the campaign; git status unchanged; nothing committed or pushed | PASS | direct-library | `evidence/src_tests_manifest_*.json` |
| ENV02 | `autocad_plot_pdf` | every PDF written in this campaign is a real one-page PDF (header %PDF-, ends with %%EOF, size > 1 kB) | PASS | file | `evidence/pdf-verification.json` |
| RP08a | `autocad_quantity_takeoff` | control: with no drawing open the takeoff itself says E_NO_ACTIVE_DOCUMENT | PASS | real-MCP-stdio+direct-COM | `09b_report_error_passthrough.jsonl#2` |
| RP08b | `autocad_check_drawing` | control: with no drawing open check_drawing itself says E_NO_ACTIVE_DOCUMENT | PASS | real-MCP-stdio | `09b_report_error_passthrough.jsonl#3` |
| RP08 | `autocad_save_report` | save_report passes the wrapped tool's typed error through (E_NO_ACTIVE_DOCUMENT) instead of E_INTERNAL | FAIL | real-MCP-stdio+direct-COM | `09b_report_error_passthrough.jsonl#4` |

## E. Cases that were run more than once (the last run counts)

| Case | Statuses in order | Why it was run again |
|---|---|---|
| HL02 | BLOCKED -> FAIL -> BLOCKED -> FAIL -> FAIL -> FAIL | first attempts used a wrong colour threshold and no redraw control (BLOCKED); later ones had a window-size dependent crop; the last run (05d) is the controlled one |
| HL02b | FAIL -> FAIL -> FAIL -> FAIL -> FAIL | same: the last run (05d) uses a window-size independent region and a regen control |
| HL19 | BLOCKED -> FAIL -> FAIL -> FAIL | see HL02 |
| HL29 | BLOCKED -> FAIL -> FAIL -> FAIL | see HL02 |
| PL00 | PASS -> PASS | identical re-run |
| PL01 | FAIL -> PASS | first run compared the layout paper strictly; the tool documents that an empty paper name is left at the device default (now compared as a documented exception and reported as OBS-plot-media-left-default) |
| PL02 | FAIL -> PASS | first run: my check read a value PL01 had not stored (harness error) |
| PL03 | PASS -> PASS | identical re-run |
| PL04 | FAIL -> PASS | first run picked the paper from a candidate list cut at 40 names; now the A3 name is asked for directly |
| PL05 | PASS -> PASS | identical re-run |
| PL06 | FAIL -> PASS | see PL01 |
| PL07 | FAIL -> PASS | see PL01 |
| PL08 | FAIL -> PASS | see PL01 |
| PL09 | PASS -> PASS | identical re-run |
| PL10 | PASS -> PASS | identical re-run |
| PL11 | PASS -> PASS | identical re-run |
| PL12 | PASS -> PASS | identical re-run |
| PL13 | PASS -> PASS | identical re-run |
| PL14 | PASS -> PASS | identical re-run |
| PL15 | PASS -> PASS | identical re-run |
| TK01 | FAIL -> PASS | first run (07_architecture.py): AutoCAD's active drawing was switched away from the pinned scratch drawing; the server refused with E_DOCUMENT_CHANGED. Re-run as 07b with a guard |
| TK02 | FAIL -> PASS | see TK01 |
| TK03 | FAIL -> PASS | see TK01 |
| TK04 | FAIL -> PASS | see TK01 |
| RP01 | FAIL -> PASS | see TK01 (and RP08: save_report re-labels the refusal as E_INTERNAL) |
| RP02 | FAIL -> PASS | see RP01 |
| RP03 | FAIL -> PASS | see RP01 |
| RP04 | FAIL -> PASS | see RP01 |
| RP05 | PASS -> PASS | identical re-run |
| RP06 | FAIL -> PASS | see RP01 |
| TO00 | PASS -> PASS | identical re-run |
| TO01 | PASS -> PASS | identical re-run |
| TO02 | PASS -> PASS | identical re-run |
| TO03 | PASS -> PASS | identical re-run |
| TO04 | FAIL -> PASS | my expectation of the worker generation was wrong (it starts at 0, the first worker is generation 1) |
| TO05 | FAIL -> PASS | my check looked for one exact message; the tool has two wordings for 'never started' |

The exploratory probe `05b_highlight_probe.py` (cases `HLP1`-`HLP3`) is left out of the totals: its pictures were taken while AutoCAD's view was still changing; `05d_highlight_visual_all.py` replaced it.

## F. Not covered by this run

* AutoCAD releases other than 2024 (R24.3), AutoCAD LT, a second AutoCAD instance, a machine without a graphics driver like this PC's Intel UHD 620.
* The cold start of `autocad_launch_application` (one attempt, crashed; the owner then started AutoCAD by hand). To retry: close AutoCAD and ask for the retry.
* A modal dialog blocking AutoCAD (`E_AUTOCAD_NOT_RESPONDING` / long timeouts were exercised only with a deliberately short limit).
* Large drawings, other plot devices than 'DWG To PDF.pc3', DWG versions written by other programs.
* `autocad_render_preview` (headless only, needs matplotlib), the OpenCode client itself.
