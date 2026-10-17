# Failures, observations and limits found live

Everything here is backed by `logs/cases.jsonl`, `logs/observations.jsonl`, the raw MCP exchanges in `logs/*.jsonl` and the files in `evidence/`. Nothing in `src/` or `tests/` was changed; fix hints are suggestions only.

## LV10: Cold start: AutoCAD crashed 3 seconds after the tool started it

* Tool: `autocad_launch_application`
* What was observed: 12:33:27 the tool called `launch_and_wait(120)`; Windows started `acad.exe`; AutoCAD's own crash reporter fired (minidump: exception 0xE0434352 = a .NET exception inside AutoCAD, parameter 0x80131534 = TypeInitializationException, session length 3 s). Windows waited until 12:34:53 (DCOM event 10010: the AutoCAD server 'did not register with DCOM within the required timeout'). The tool answered `connected:false, running:false, verified:false`, message `Failed to launch AutoCAD via COM: (-2146959355, 'Server execution failed', None, None)` after 88.8 s.
* Cause: The tool reported the failure correctly and did not hang (88.8 s < its 120 s limit). The cause is inside AutoCAD's start-up, not shown to be in this server. It is unknown whether it repeats: one attempt only. On 2026-10-16 the same function started AutoCAD fine (docs/testing.md), and AutoCAD started by hand was running and answering COM by 12:39 (pid 15472) and stayed up. Another acad.exe (pid 14452) ran for about 37 s at 12:36 and was not started by this campaign.
* Notes: Evidence: `logs/01_launch.*`, `evidence/launch-crash/` (cer.log, launch-crash-facts.json). Retry idea: close AutoCAD, run `01_launch.py` again; if it crashes again, compare with a start from the Start menu and check the graphics driver (Intel UHD 620 reported 'no hardware acceleration' in the crash report).

## TD02 / TD04: Intermittent E_INTERNAL 'AttributeError: AddLine.Handle' after the drawing was saved

* Tool: `autocad_create_test_drawing_with_line`
* What was observed: 2 of 13 calls failed (TD02 and call 3 of the 10 repeats, `evidence/04b_testdrawing_repeat.json`). Each failed call had already saved a valid DWG (header AC1032, about 16 kB, checked) and left its drawing open; the caller got `E_INTERNAL` (recoverable false, 'report a bug') and no handle.
* Cause: `src/tools/primitives.py` reads `line.ObjectName` (line 349) and `line.Handle` (line 366) without `_retry_com`. `_retry_com`'s own docstring describes this exact transient AttributeError from win32com while AutoCAD is busy (right after SaveAs). `draw_line` (lines 129, 136) and `draw_polyline` (170, 177) read `.Handle` the same way; they did not fail in about 45 calls here, but carry the same risk.
* Notes: Fix hint: wrap the two property reads in `_retry_com`. TD01 (first call) passed all checks: file under output_dir, DWG header AC1032, one line (0,0,0)-(100,100,0) with the reported handle.

## TD03: output_dir is not checked against AUTOCAD_MCP_ALLOWED_DIRS

* Tool: `autocad_create_test_drawing_with_line`
* What was observed: With the server limited to the run's `workspace` folder, `output_dir=<run>/outside_sandbox/test-drawings` succeeded and wrote a DWG there.
* Cause: `create_test_drawing_with_line` does `os.makedirs(output_dir)` and `SaveAs` without `core.paths.output_path`; AGENTS.md invariant 8 says never write outside the allowed folders. Every other file-writing tool in this run (plot, export, save, reports, open) refused such paths.
* Notes: Fix hint: validate `output_dir` like the other tools. Harmless here (the folder is inside this run folder).

## HL02 / HL19 / HL29: Temporary highlight is not visible on AutoCAD's screen

* Tool: `autocad_highlight_entity, autocad_highlight_text_matches, autocad_query_and_highlight`
* What was observed: Controlled pictures of AutoCAD's own window (`evidence/highlight_visual/`, numbers in `evidence/highlight_visual.json`): AutoCAD's own `entity.Highlight(True)` through COM adds 2,873 highlight-coloured pixels; `Highlight(True)` followed by `doc.Regen(1)` adds 0; the three tools add 0 (and clearing leaves 0). The tools answer `highlighted:true` and honestly `verified:false` ('not readable over COM').
* Cause: All three tools call `Highlight(...)` and then `_regen(doc)` (`src/tools/editing.py` lines 200, 295-296, 371-372). On AutoCAD 2024 the regen removes the highlight that was just set.
* Notes: Fix hint: drop the regen after Highlight (or use `entity.Update()`), then re-run `05d_highlight_visual_all.py`: the control numbers show what a working highlight looks like.

## HL02b: Persistent colour is stored but not repainted

* Tool: `autocad_highlight_entity`
* What was observed: Read back over COM the colour is correct (HL04, HL05, HL14, HL22). On screen: 0 red pixels right after the call, +444 after a regen done by the harness.
* Cause: The persistent branch sets `entity.Color` and never asks AutoCAD to redraw.
* Notes: Fix hint: `entity.Update()` or a regen after the colour change. Severity: medium (the tool's purpose is to show the user something).

## RP08: A typed error of the wrapped tool is re-labelled E_INTERNAL

* Tool: `autocad_save_report`
* What was observed: With no drawing open, `autocad_check_drawing` and `autocad_quantity_takeoff` both answer `E_NO_ACTIVE_DOCUMENT`; `autocad_save_report` answers `E_INTERNAL`, message `ToolError: {... E_NO_ACTIVE_DOCUMENT ...}`, recoverable false, action 'report a bug'. The same happened for real with `E_DOCUMENT_CHANGED` in the first 07 run (RP01-RP04, RP06).
* Cause: `server.py` `autocad_save_report` calls the decorated `autocad_check_drawing` / `autocad_quantity_takeoff`; their `ToolError` is caught again by the outer wrapper.
* Notes: Fix hint: call the undecorated implementation, or re-raise `ToolError` unchanged. It is backend independent, so a headless test can cover it too.

## Observations (not counted as failures)

* **OBS-testdrawing-path-policy** (medium, `autocad_create_test_drawing_with_line`): autocad_create_test_drawing_with_line writes to any output_dir; core.paths.output_path (allowed-folder policy) is not applied.  
  Evidence: `{"status": "ok", "file_path": "C:\\Users\\This PC\\Desktop\\Autocad Mcp Server\\.claude\\worktrees\\elated-austin-a13117\\test-results\\v0.3.0\\live-run-20261017-123014\\outside_sandbox\\test-drawings\\mcp_test_20261017_124942_342114.dwg", "line_handle": "7E", "start_point": [0.0, 0.0, 0.0], "end_po`
* **OBS-query-highlight-scope** (medium, `autocad_query_and_highlight`): query_and_highlight is not scoped to the active drawing: a scan row of drawing A (layer MCP_H) coloured an unrelated circle on layer MCP_OTHER in drawing B because both drawings give the same handle.  
  Evidence: `{"handles_in_drawing_A": {"L1": "7E", "L2": "7F", "C1": "80", "T1": "82", "T2": "83", "T3": "84", "T4": "85", "M1": "86"}, "handles_in_drawing_B": {"L1": "7E", "L2": "7F", "C1": "80"}, "identical_handles": {"L1": ["7E", "7E"], "L2": ["7F", "7F"], "C1": ["80", "80"]}, "query_result": {"status": "ok",`
* **OBS-plot-media-left-default** (low, `autocad_plot_pdf`): A layout whose paper (CanonicalMediaName) was never set ('') keeps a different value after autocad_plot_pdf; the result says layout_settings_restored=true and lists the key only in layout_settings_left_at_device_default.  
  Evidence: `layout Model CanonicalMediaName: '' -> 'Sun_Hi-Res_(1600.00_x_1280.00_Pixels)'`
* **OBS-save-report-error-wrap** (medium, `autocad_save_report`): autocad_save_report calls the decorated autocad_check_drawing / autocad_quantity_takeoff functions; their ToolError is caught by its own wrapper and re-classified as E_INTERNAL (recoverable=false, 'report a bug'). Every typed error of the wrapped tools (E_NO_ACTIVE_DOCUMENT, E_DOCUMENT_CHANGED, E_AUTOCAD_NOT_RUNNING ...) is lost.  
  Evidence: `{"ok": false, "error": {"code": "E_INTERNAL", "message": "ToolError: {\"ok\": false, \"error\": {\"code\": \"E_NO_ACTIVE_DOCUMENT\", \"message\": \"No document is open in AutoCAD. Call autocad_create_new_drawing or open a drawing first.\", \"recoverable\": true, \"recommended_action\": \"call_autoca`
* **OBS-pytest-fatal-exception-noise** (info): the project's own live test run printed `Windows fatal exception: code 0x80010001` 40 times with Python stack traces while every test passed. It is Python's faulthandler reporting AutoCAD's 'call rejected, busy' replies that the server's retry loop handles; it is noise, not a crash (`logs/pytest-live-integration.txt`).
* **OBS-pin-worked-for-real** (info): during the first 07 run AutoCAD's active drawing was switched to another scratch drawing about two seconds after the last draw (not by the server; the cause was not established, somebody clicking another drawing tab is the likely explanation). The pin refused the 10 following calls that touched the drawing with `E_DOCUMENT_CHANGED` ('Nothing was changed'; four of them reached the client as E_INTERNAL because of RP08), as designed (`logs/07_architecture.jsonl` seq 31-41).
* **OBS-owner-touched-window** (info): the AutoCAD window changed size between steps (window pictures grew from 750 x 720 to 1382 x 736 px; probably maximised by the owner), so the window-picture checks use a region relative to the window size.
