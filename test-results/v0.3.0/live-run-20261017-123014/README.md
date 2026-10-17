# Live test of the AutoCAD MCP server against a real AutoCAD 2024

**AutoCAD release string:** `24.3s (LMS Tech)` (AutoCAD 2024, `acad.exe` R24.3.61.0.0). Everything below was run on a real AutoCAD through the real MCP client, on scratch drawings only. Nothing in `src/` or `tests/` was changed; nothing was committed or pushed.

## In plain words

* **The project's own live test file passed completely:** 19 of 19 tests (`logs/pytest-live-integration.txt`).
* **My own live checks:** 138 passed, 9 failed, 0 blocked, out of 148 cases (one case is information only). Details per tool: `live-results.md`.
* **`autocad_plot_pdf` works.** Real one-page PDFs (checked by header, size, page count, page size and drawing content), paper and plot style selection work, AutoCAD's settings are put back.
* **Open / activate / pin / save / close with two scratch drawings work,** including the case where somebody clicks another drawing tab (the pin stops every tool and nothing is drawn in the wrong drawing).
* **Layer property changes, stair, sheet and takeoff tools work.** Every number was checked against values computed by hand or read straight from AutoCAD.
* **The COM timeout path works** against a real, slow AutoCAD.
* **What did not work (the owner should know):**
  1. **`autocad_launch_application` could not start AutoCAD from nothing.** AutoCAD crashed itself 3 seconds after the tool started it. The tool reported this honestly. Started by hand, AutoCAD ran fine, and the tool then correctly only checks it. Only one attempt; it is not known if it repeats.
  2. **The highlight tools show nothing on screen.** `autocad_highlight_entity`, `autocad_highlight_text_matches` and `autocad_query_and_highlight` select the right things and say success, but in AutoCAD 2024 the highlight is wiped by the redraw the tools do right after it. A permanent colour change is stored but only appears at the next redraw.
  3. **`autocad_create_test_drawing_with_line` is flaky** (2 of 13 calls ended with an internal error after saving the file) **and ignores the allowed-folder setting.**
  4. **`autocad_save_report` hides the real error** (shows `E_INTERNAL` where the wrapped tool says, for example, no drawing is open).
* Two smaller notes: `autocad_query_and_highlight` is not limited to the active drawing, and after a plot an unset paper name stays changed (low).

## State at the end

AutoCAD is still running: the owner started it by hand after the tool-started launch crashed, so I did not close it. No drawing of this campaign is open in it any more (checked by reading AutoCAD's drawing list). `src/` and `tests/` are byte-identical to before and `git status` of the repository is unchanged (`evidence/src_tests_manifest_*.json`, `evidence/git_status_*.txt`).

## What to do next (one step)

Ask for the four problems in "What did not work" to be fixed in `src/`; then re-run `05d_highlight_visual_all.py` and `04b_testdrawing_repeat.py` here (a few minutes with AutoCAD open) to prove it. To retry the automatic start: close AutoCAD, then run `harness\01_launch.py` again.

## Where things are

| Path | What it is |
|---|---|
| `live-results.md`, `live-results.json` | per-tool and per-case PASS / FAIL / BLOCKED results |
| `failures-and-observations.md` | every failure with evidence, cause and a fix hint |
| `environment-live.md` | exact versions, how the run was set up |
| `logs/` | raw MCP exchanges (`*.jsonl`), server error output, console output of every script, `cases.jsonl`, `observations.jsonl`, `pytest-live-integration.txt` |
| `evidence/` | release strings, crash facts, pictures of AutoCAD's window, PDF checks, before/after file hashes of `src/` and `tests/` |
| `workspace/` | every file the server wrote (DWG, DXF, PDF, reports, SQLite) |
| `pytest-tmp/` | files written by the project's own live tests |
| `harness/` | the scripts, in the order they were run (`00`...`10`) |

## Honest limits

Results are for AutoCAD 2024 (R24.3) on this PC only. The six tools are no longer 'blocked', but the cold start, other releases, a second AutoCAD, large drawings and a dialog blocking AutoCAD are not covered (see `live-results.md` section F). The first run of several cases failed because of my own wrong expectations or because somebody clicked another tab; those first runs stay in `logs/cases.jsonl` and are listed in `live-results.md` section E.

This folder lives in the git worktree of this session; to put it next to the older runs, copy it: `Copy-Item -Recurse "<worktree>\test-results\v0.3.0\live-run-20261017-123014" "C:\Users\This PC\Desktop\Autocad Mcp Server\test-results\v0.3.0\"`.
