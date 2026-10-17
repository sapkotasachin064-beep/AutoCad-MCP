# Environment of the live run

* Date: 2026-10-17 (clock of this PC: NST, UTC+05:45).
* AutoCAD: `24.3s (LMS Tech)`; `ACADVER` `24.3s (LMS Tech)`; `_VERNUM` `U.61.0.0 (UNICODE)`; `acad.exe` file version `R24.3.61.0.0`; ProgID `AutoCAD.Application.24`.
* AutoCAD was started by the owner by hand at about 12:39 (pid 15472) after the tool-started launch crashed at 12:33; it was still running, with no drawing open, at the end. Nothing of this campaign is left open in it.
* Windows: Windows-11-10.0.26300-SP0. Python (system): 3.14.7 (`C:\Users\This PC\AppData\Local\Programs\Python\Python314\python.exe`). Packages: {'mcp': '2.3.0', 'pywin32': '312', 'pytest': '9.1.1', 'ezdxf': '1.4.4', 'pillow': '12.3.0', 'pdfplumber': '0.11.10'}.
* Code under test: base checkout `C:\Users\This PC\Desktop\Autocad Mcp Server`, branch `feat/v0.3.0-rebuild`, HEAD `c591f7a2c181ac613081fb936d686961ebb32ac2 fix: live AutoCAD 2024 findings; record live-verified capabilities`, with the uncommitted changes listed in `evidence/git_status_before.txt` (same list after the run). `src/` and `tests/` hashed before and after: identical.
* Server: `src/server.py` started by the official MCP client over stdio with `AUTOCAD_MCP_BACKEND=com`, `AUTOCAD_MCP_OUTPUT_DIR` and `AUTOCAD_MCP_ALLOWED_DIRS` = this run's `workspace/`, `AUTOCAD_MCP_DB_PATH` = `workspace/autocad_mcp_live.db`, COM timeout 120 s (1.0 s in the timeout test).
* Live test file: run from the base checkout's `tests/test_integration_autocad.py` with `-p no:cacheprovider --rootdir/-c <repo>/pyproject.toml --basetemp=<run>/pytest-tmp --junitxml=...` so nothing was written into the repository.
* Screen: 1366 x 768, Intel UHD Graphics 620; AutoCAD's crash report says hardware acceleration was not available.
* Only scratch drawings created by the scripts were used (they are closed again); no real project drawing was opened. Files written by the tools are under `workspace/`, `pytest-tmp/` and `evidence/`.
* Files stay inside this run folder, which lives in the git worktree of this session (the base checkout is write-protected for this session): `C:\Users\This PC\Desktop\Autocad Mcp Server\.claude\worktrees\elated-austin-a13117\test-results\v0.3.0\live-run-20261017-123014
