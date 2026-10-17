"""Step 10 - build the result files of the live campaign from logs/cases.jsonl, logs/observations.jsonl and evidence/.

Rule: for a case id that was run more than once, the LAST record is the result; earlier records are kept in
logs/cases.jsonl and listed in live-results.md ("earlier attempts") with the reason they were replaced.
"""

import hashlib
import json
import sys
import time
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_harness as h  # noqa: E402

RUN = h.RUN
LOGS, EV = h.LOGS, h.EVIDENCE
SIX = ["autocad_launch_application", "autocad_create_test_drawing_with_line", "autocad_highlight_entity",
       "autocad_highlight_text_matches", "autocad_query_and_highlight", "autocad_plot_pdf"]
EXTRA = [("Open / activate / pin / save / close (two scratch drawings)", ["autocad_create_new_drawing", "autocad_list_drawings", "autocad_open_drawing", "autocad_activate_drawing", "autocad_pin_document",
                                                                          "autocad_unpin_document", "autocad_save_drawing", "autocad_close_drawing"]),
         ("Layer property changes", ["autocad_set_layer_properties", "autocad_create_layer", "autocad_list_layers"]),
         ("Stair", ["autocad_design_stair", "autocad_draw_stair_plan"]),
         ("Sheet and title block", ["autocad_draw_sheet"]),
         ("Takeoff, checks and saved reports", ["autocad_quantity_takeoff", "autocad_check_drawing", "autocad_save_report", "autocad_scan_all_entities"]),
         ("Layouts and DXF export", ["autocad_list_layouts", "autocad_export_dxf"]),
         ("COM timeout path", ["autocad_get_capabilities"]),
         ("Status", ["autocad_get_status"])]
SUPERSEDED_WHY = {
    "HL02": "first attempts used a wrong colour threshold and no redraw control (BLOCKED); later ones had a window-size dependent crop; the last run (05d) is the controlled one",
    "HL02b": "same: the last run (05d) uses a window-size independent region and a regen control",
    "HL19": "see HL02", "HL29": "see HL02",
    "PL01": "first run compared the layout paper strictly; the tool documents that an empty paper name is left at the device default (now compared as a documented exception and reported as OBS-plot-media-left-default)",
    "PL02": "first run: my check read a value PL01 had not stored (harness error)", "PL04": "first run picked the paper from a candidate list cut at 40 names; now the A3 name is asked for directly",
    "PL06": "see PL01", "PL07": "see PL01", "PL08": "see PL01",
    "TK01": "first run (07_architecture.py): AutoCAD's active drawing was switched away from the pinned scratch drawing; the server refused with E_DOCUMENT_CHANGED. Re-run as 07b with a guard",
    "TK02": "see TK01", "TK03": "see TK01", "TK04": "see TK01", "RP01": "see TK01 (and RP08: save_report re-labels the refusal as E_INTERNAL)", "RP02": "see RP01", "RP03": "see RP01", "RP04": "see RP01", "RP06": "see RP01",
    "TO04": "my expectation of the worker generation was wrong (it starts at 0, the first worker is generation 1)", "TO05": "my check looked for one exact message; the tool has two wordings for 'never started'",
}
EXPLORATORY = ("HLP",)  # 05b probe: superseded by the controlled picture test 05d

PLAIN = {
    "autocad_launch_application": ("FAIL (cold start) / PASS (AutoCAD already running)",
                                   "Could not start AutoCAD from nothing: AutoCAD crashed itself about 3 seconds after the tool started it (AutoCAD's own .NET start-up error), and the tool said so honestly after 89 s. Started by hand, AutoCAD ran fine; calling the tool then only checks it and touches nothing. One attempt, not retried."),
    "autocad_create_test_drawing_with_line": ("FAIL",
                                              "Draws the line at (0,0)-(100,100), saves a real DWG and the file matches. But 2 of 13 calls failed with an internal error after the file was already saved, and it writes to any folder, ignoring the allowed-folder setting."),
    "autocad_highlight_entity": ("FAIL",
                                 "Argument checks, colour change and read-back work. The 'temporary' highlight is not visible on AutoCAD's screen (the tool's own redraw wipes it), and a 'persistent' colour is stored but only shows after the next redraw."),
    "autocad_highlight_text_matches": ("FAIL",
                                       "Finds exactly the right TEXT/MTEXT, never changes the text, limit/regex/clear handled. The highlight itself is not visible on screen (same cause as highlight_entity)."),
    "autocad_query_and_highlight": ("FAIL",
                                    "Query rules, stale handles and error codes work. The highlight is not visible on screen, and rows from another drawing's scan can recolour unrelated entities in the active drawing."),
    "autocad_plot_pdf": ("PASS",
                         "Real one-page PDFs from model space and a layout, correct page size for the chosen paper, plot style applied, refusals clean, AutoCAD's plot settings restored (one low-severity note about an unset paper name)."),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases():
    rows = [json.loads(l) for l in (LOGS / "cases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    last, hist = OrderedDict(), defaultdict(list)
    for r in rows:
        hist[r["id"]].append(r)
        last[r["id"]] = r
    return rows, last, hist


def status_of(group: list[dict]) -> str:
    if any(c["status"] == "FAIL" for c in group):
        return "FAIL"
    if any(c["status"] == "PASS" for c in group):
        return "PASS"
    if any(c["status"] == "BLOCKED" for c in group):
        return "BLOCKED"
    return "NOT_ATTEMPTED"


def esc(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def main():
    rows, last, hist = load_cases()
    obs = [json.loads(l) for l in (LOGS / "observations.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rel = json.loads((EV / "autocad_release_final.json").read_text(encoding="utf-8"))
    final = {k: v for k, v in last.items() if not k.startswith(EXPLORATORY)}
    by_tool = defaultdict(list)
    for c in final.values():
        by_tool[c.get("tool")].append(c)
    counts = Counter(c["status"] for c in final.values())
    release = rel.get("Application.Version")

    # ------------------------------------------------------------------------ json
    tools_json = {}
    for name in SIX:
        g = by_tool.get(name, [])
        tools_json[name] = {"status": PLAIN[name][0], "rule_status": status_of(g), "cases": {s: sum(1 for c in g if c["status"] == s) for s in ("PASS", "FAIL", "BLOCKED", "NOT_ATTEMPTED")},
                            "case_ids": [c["id"] for c in g], "summary": PLAIN[name][1]}
    h.dump(RUN / "live-results.json", {
        "run_folder": RUN.name, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "autocad": {"release_string": release, "ACADVER": rel.get("ACADVER"), "_VERNUM": rel.get("var._VERNUM"), "PRODUCT": rel.get("var.PRODUCT"),
                                                                                         "acad_exe_file_version": "R24.3.61.0.0", "window_title": "Autodesk AutoCAD 2024", "started_by": "the owner, by hand (the tool-started launch crashed)"},
        "totals": dict(counts), "tools": tools_json, "cases": list(final.values()), "observations": obs,
        "earlier_attempts": {k: [r["status"] for r in v] for k, v in hist.items() if len(v) > 1}})

    # ------------------------------------------------------------------------ live-results.md
    L = []
    L.append(f"# Live results: AutoCAD MCP v0.3.0 against a real AutoCAD\n")
    L.append(f"Run folder: `{RUN.name}`. Every result below was produced by a real AutoCAD, never by fake COM or the headless DXF backend.\n")
    L.append(f"**AutoCAD release string (exact):** `{release}` (`Application.Version` and `ACADVER` agree). `_VERNUM` = `{rel.get('var._VERNUM')}`, product `{rel.get('var.PRODUCT')}`, "
             f"`acad.exe` file version `R24.3.61.0.0`, window title `Autodesk AutoCAD 2024`. Windows 11 Pro 10.0.26300, Python 3.14.7, mcp 2.3.0, pywin32 312.\n")
    L.append(f"**Totals (final result per case id, {len(final)} cases):** " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) + ". "
             "Plus the project's own live test file: 19 passed, 0 failed (`pytest-live-integration.txt`).\n")
    L.append("## A. The six tools that could not be tested headless\n")
    L.append("| Tool | Result | Cases (pass / fail) | What it means |\n|---|---|---|---|")
    for name in SIX:
        g = by_tool.get(name, [])
        p, f = sum(1 for c in g if c["status"] == "PASS"), sum(1 for c in g if c["status"] == "FAIL")
        L.append(f"| `{name}` | **{PLAIN[name][0]}** | {p} / {f} | {esc(PLAIN[name][1])} |")
    L.append("\nNone of the six stayed BLOCKED. The cold-start half of `autocad_launch_application` is the only part that could not be verified (AutoCAD crashed on its own).\n")
    L.append("## B. Also requested\n")
    L.append("| Area | Result | Cases (pass / fail) | Tools |\n|---|---|---|---|")
    for title, tools in EXTRA:
        g = [c for t in tools for c in by_tool.get(t, []) if not (t == "autocad_get_capabilities" and not c["id"].startswith("TO"))]
        if title == "COM timeout path":
            g = [c for c in final.values() if c["id"].startswith("TO")]
        if title == "Status":
            g = [c for c in final.values() if c["id"] in ("LV01", "LV02", "LV12", "LV13", "LV20", "LV21", "LV22", "LV23")]
        if not g:
            continue
        p, f = sum(1 for c in g if c["status"] == "PASS"), sum(1 for c in g if c["status"] == "FAIL")
        L.append(f"| {title} | **{status_of(g)}** | {p} / {f} | {', '.join('`' + t + '`' for t in tools if by_tool.get(t))} |")
    L.append("")
    L.append("## C. Failed or unverified, with the evidence\n")
    L.append("| Case | Tool | Status | Why (evidence) |\n|---|---|---|---|")
    for c in final.values():
        if c["status"] in ("FAIL", "BLOCKED"):
            L.append(f"| {c['id']} | `{c.get('tool')}` | {c['status']} | {esc('; '.join(c.get('problems') or []) or c.get('evidence', ''))[:700]} |")
    L.append("")
    L.append("## D. Every final case\n")
    L.append("| Case | Tool / area | Title | Status | Method | Raw log |\n|---|---|---|---|---|---|")
    for c in final.values():
        L.append(f"| {c['id']} | `{c.get('tool') or c.get('area') or ''}` | {esc(c.get('title', ''))} | {c['status']} | {c.get('method', '')} | `{c.get('log_ref', '')}` |")
    L.append("")
    L.append("## E. Cases that were run more than once (the last run counts)\n")
    L.append("| Case | Statuses in order | Why it was run again |\n|---|---|---|")
    for k, v in hist.items():
        if len(v) > 1 and not k.startswith(EXPLORATORY):
            L.append(f"| {k} | {' -> '.join(r['status'] for r in v)} | {esc(SUPERSEDED_WHY.get(k, 'identical re-run'))} |")
    L.append("\nThe exploratory probe `05b_highlight_probe.py` (cases `HLP1`-`HLP3`) is left out of the totals: its pictures were taken while AutoCAD's view was still changing; `05d_highlight_visual_all.py` replaced it.\n")
    L.append("## F. Not covered by this run\n")
    for line in ("AutoCAD releases other than 2024 (R24.3), AutoCAD LT, a second AutoCAD instance, a machine without a graphics driver like this PC's Intel UHD 620.",
                 "The cold start of `autocad_launch_application` (one attempt, crashed; the owner then started AutoCAD by hand). To retry: close AutoCAD and ask for the retry.",
                 "A modal dialog blocking AutoCAD (`E_AUTOCAD_NOT_RESPONDING` / long timeouts were exercised only with a deliberately short limit).",
                 "Large drawings, other plot devices than 'DWG To PDF.pc3', DWG versions written by other programs.",
                 "`autocad_render_preview` (headless only, needs matplotlib), the OpenCode client itself."):
        L.append(f"* {line}")
    (RUN / "live-results.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------------ failures-and-observations.md
    F = ["# Failures, observations and limits found live\n",
         "Everything here is backed by `logs/cases.jsonl`, `logs/observations.jsonl`, the raw MCP exchanges in `logs/*.jsonl` and the files in `evidence/`. Nothing in `src/` or `tests/` was changed; fix hints are suggestions only.\n"]
    FAILS = [
        ("LV10", "autocad_launch_application", "Cold start: AutoCAD crashed 3 seconds after the tool started it",
         "12:33:27 the tool called `launch_and_wait(120)`; Windows started `acad.exe`; AutoCAD's own crash reporter fired (minidump: exception 0xE0434352 = a .NET exception inside AutoCAD, parameter 0x80131534 = TypeInitializationException, session length 3 s). Windows waited until 12:34:53 (DCOM event 10010: the AutoCAD server 'did not register with DCOM within the required timeout'). The tool answered `connected:false, running:false, verified:false`, message `Failed to launch AutoCAD via COM: (-2146959355, 'Server execution failed', None, None)` after 88.8 s.",
         "The tool reported the failure correctly and did not hang (88.8 s < its 120 s limit). The cause is inside AutoCAD's start-up, not shown to be in this server. It is unknown whether it repeats: one attempt only. On 2026-10-16 the same function started AutoCAD fine (docs/testing.md), and AutoCAD started by hand was running and answering COM by 12:39 (pid 15472) and stayed up. Another acad.exe (pid 14452) ran for about 37 s at 12:36 and was not started by this campaign.",
         "Evidence: `logs/01_launch.*`, `evidence/launch-crash/` (cer.log, launch-crash-facts.json). Retry idea: close AutoCAD, run `01_launch.py` again; if it crashes again, compare with a start from the Start menu and check the graphics driver (Intel UHD 620 reported 'no hardware acceleration' in the crash report)."),
        ("TD02 / TD04", "autocad_create_test_drawing_with_line", "Intermittent E_INTERNAL 'AttributeError: AddLine.Handle' after the drawing was saved",
         "2 of 13 calls failed (TD02 and call 3 of the 10 repeats, `evidence/04b_testdrawing_repeat.json`). Each failed call had already saved a valid DWG (header AC1032, about 16 kB, checked) and left its drawing open; the caller got `E_INTERNAL` (recoverable false, 'report a bug') and no handle.",
         "`src/tools/primitives.py` reads `line.ObjectName` (line 349) and `line.Handle` (line 366) without `_retry_com`. `_retry_com`'s own docstring describes this exact transient AttributeError from win32com while AutoCAD is busy (right after SaveAs). `draw_line` (lines 129, 136) and `draw_polyline` (170, 177) read `.Handle` the same way; they did not fail in about 45 calls here, but carry the same risk.",
         "Fix hint: wrap the two property reads in `_retry_com`. TD01 (first call) passed all checks: file under output_dir, DWG header AC1032, one line (0,0,0)-(100,100,0) with the reported handle."),
        ("TD03", "autocad_create_test_drawing_with_line", "output_dir is not checked against AUTOCAD_MCP_ALLOWED_DIRS",
         "With the server limited to the run's `workspace` folder, `output_dir=<run>/outside_sandbox/test-drawings` succeeded and wrote a DWG there.",
         "`create_test_drawing_with_line` does `os.makedirs(output_dir)` and `SaveAs` without `core.paths.output_path`; AGENTS.md invariant 8 says never write outside the allowed folders. Every other file-writing tool in this run (plot, export, save, reports, open) refused such paths.",
         "Fix hint: validate `output_dir` like the other tools. Harmless here (the folder is inside this run folder)."),
        ("HL02 / HL19 / HL29", "autocad_highlight_entity, autocad_highlight_text_matches, autocad_query_and_highlight", "Temporary highlight is not visible on AutoCAD's screen",
         "Controlled pictures of AutoCAD's own window (`evidence/highlight_visual/`, numbers in `evidence/highlight_visual.json`): AutoCAD's own `entity.Highlight(True)` through COM adds 2,873 highlight-coloured pixels; `Highlight(True)` followed by `doc.Regen(1)` adds 0; the three tools add 0 (and clearing leaves 0). The tools answer `highlighted:true` and honestly `verified:false` ('not readable over COM').",
         "All three tools call `Highlight(...)` and then `_regen(doc)` (`src/tools/editing.py` lines 200, 295-296, 371-372). On AutoCAD 2024 the regen removes the highlight that was just set.",
         "Fix hint: drop the regen after Highlight (or use `entity.Update()`), then re-run `05d_highlight_visual_all.py`: the control numbers show what a working highlight looks like."),
        ("HL02b", "autocad_highlight_entity", "Persistent colour is stored but not repainted",
         "Read back over COM the colour is correct (HL04, HL05, HL14, HL22). On screen: 0 red pixels right after the call, +444 after a regen done by the harness.",
         "The persistent branch sets `entity.Color` and never asks AutoCAD to redraw.",
         "Fix hint: `entity.Update()` or a regen after the colour change. Severity: medium (the tool's purpose is to show the user something)."),
        ("RP08", "autocad_save_report", "A typed error of the wrapped tool is re-labelled E_INTERNAL",
         "With no drawing open, `autocad_check_drawing` and `autocad_quantity_takeoff` both answer `E_NO_ACTIVE_DOCUMENT`; `autocad_save_report` answers `E_INTERNAL`, message `ToolError: {... E_NO_ACTIVE_DOCUMENT ...}`, recoverable false, action 'report a bug'. The same happened for real with `E_DOCUMENT_CHANGED` in the first 07 run (RP01-RP04, RP06).",
         "`server.py` `autocad_save_report` calls the decorated `autocad_check_drawing` / `autocad_quantity_takeoff`; their `ToolError` is caught again by the outer wrapper.",
         "Fix hint: call the undecorated implementation, or re-raise `ToolError` unchanged. It is backend independent, so a headless test can cover it too."),
    ]
    for cid, tool_name, title, evidence, cause, hint in FAILS:
        F.append(f"## {cid}: {title}\n\n* Tool: `{tool_name}`\n* What was observed: {evidence}\n* Cause: {cause}\n* Notes: {hint}\n")
    F.append("## Observations (not counted as failures)\n")
    for o in obs:
        F.append(f"* **{o['id']}** ({o['severity']}, `{o.get('tool')}`): {o['text']}  \n  Evidence: `{o.get('evidence', '')[:300]}`")
    F.append("* **OBS-pytest-fatal-exception-noise** (info): the project's own live test run printed `Windows fatal exception: code 0x80010001` 40 times with Python stack traces while every test passed. It is Python's faulthandler reporting AutoCAD's 'call rejected, busy' replies that the server's retry loop handles; it is noise, not a crash (`logs/pytest-live-integration.txt`).")
    F.append("* **OBS-pin-worked-for-real** (info): during the first 07 run AutoCAD's active drawing was switched to another scratch drawing about two seconds after the last draw (not by the server; the cause was not established, somebody clicking another drawing tab is the likely explanation). The pin refused the 10 following calls that touched the drawing with `E_DOCUMENT_CHANGED` ('Nothing was changed'; four of them reached the client as E_INTERNAL because of RP08), as designed (`logs/07_architecture.jsonl` seq 31-41).")
    F.append("* **OBS-owner-touched-window** (info): the AutoCAD window changed size between steps (window pictures grew from 750 x 720 to 1382 x 736 px; probably maximised by the owner), so the window-picture checks use a region relative to the window size.")
    (RUN / "failures-and-observations.md").write_text("\n".join(F) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------------ environment-live.md
    pre = json.loads((EV / "preflight.json").read_text(encoding="utf-8"))
    E = ["# Environment of the live run\n",
         f"* Date: 2026-10-17 (clock of this PC: NST, UTC+05:45).",
         f"* AutoCAD: `{release}`; `ACADVER` `{rel.get('ACADVER')}`; `_VERNUM` `{rel.get('var._VERNUM')}`; `acad.exe` file version `{pre['acad_exe_file_version']['FileVersion']}`; ProgID `{pre['registry_ProgID_CurVer']}`.",
         "* AutoCAD was started by the owner by hand at about 12:39 (pid 15472) after the tool-started launch crashed at 12:33; it was still running, with no drawing open, at the end. Nothing of this campaign is left open in it.",
         f"* Windows: {pre['windows']}. Python (system): 3.14.7 (`{pre['system_python_exe']}`). Packages: {pre['packages']}.",
         f"* Code under test: base checkout `C:\\Users\\This PC\\Desktop\\Autocad Mcp Server`, branch `{pre['git_branch']}`, HEAD `{pre['git_head']}`, with the uncommitted changes listed in `evidence/git_status_before.txt` (same list after the run). `src/` and `tests/` hashed before and after: identical.",
         "* Server: `src/server.py` started by the official MCP client over stdio with `AUTOCAD_MCP_BACKEND=com`, `AUTOCAD_MCP_OUTPUT_DIR` and `AUTOCAD_MCP_ALLOWED_DIRS` = this run's `workspace/`, `AUTOCAD_MCP_DB_PATH` = `workspace/autocad_mcp_live.db`, COM timeout 120 s (1.0 s in the timeout test).",
         "* Live test file: run from the base checkout's `tests/test_integration_autocad.py` with `-p no:cacheprovider --rootdir/-c <repo>/pyproject.toml --basetemp=<run>/pytest-tmp --junitxml=...` so nothing was written into the repository.",
         "* Screen: 1366 x 768, Intel UHD Graphics 620; AutoCAD's crash report says hardware acceleration was not available.",
         "* Only scratch drawings created by the scripts were used (they are closed again); no real project drawing was opened. Files written by the tools are under `workspace/`, `pytest-tmp/` and `evidence/`.",
         "* Files stay inside this run folder, which lives in the git worktree of this session (the base checkout is write-protected for this session): `C:\\Users\\This PC\\Desktop\\Autocad Mcp Server\\.claude\\worktrees\\elated-austin-a13117\\test-results\\v0.3.0\\" + RUN.name]
    (RUN / "environment-live.md").write_text("\n".join(E) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------------ README.md (plain language)
    mine = [c for c in final.values() if not c['id'].startswith('PT-')]
    mine_counts = Counter(c['status'] for c in mine)
    R = f"""# Live test of the AutoCAD MCP server against a real AutoCAD 2024

**AutoCAD release string:** `{release}` (AutoCAD 2024, `acad.exe` R24.3.61.0.0). Everything below was run on a real AutoCAD through the real MCP client, on scratch drawings only. Nothing in `src/` or `tests/` was changed; nothing was committed or pushed.

## In plain words

* **The project's own live test file passed completely:** 19 of 19 tests (`logs/pytest-live-integration.txt`).
* **My own live checks:** {mine_counts.get('PASS', 0)} passed, {mine_counts.get('FAIL', 0)} failed, {mine_counts.get('BLOCKED', 0)} blocked, out of {len(mine)} cases (one case is information only). Details per tool: `live-results.md`.
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

Ask for the four problems in "What did not work" to be fixed in `src/`; then re-run `05d_highlight_visual_all.py` and `04b_testdrawing_repeat.py` here (a few minutes with AutoCAD open) to prove it. To retry the automatic start: close AutoCAD, then run `harness\\01_launch.py` again.

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

This folder lives in the git worktree of this session; to put it next to the older runs, copy it: `Copy-Item -Recurse "<worktree>\\test-results\\v0.3.0\\{RUN.name}" "C:\\Users\\This PC\\Desktop\\Autocad Mcp Server\\test-results\\v0.3.0\\"`.
"""
    (RUN / "README.md").write_text(R, encoding="utf-8")

    # ------------------------------------------------------------------------ manifest
    files = []
    for p in sorted(RUN.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            files.append({"path": str(p.relative_to(RUN)).replace("\\", "/"), "bytes": p.stat().st_size, "sha256": sha(p)})
    h.dump(RUN / "output-manifest.json", files)
    print(f"cases: {len(final)} final ({dict(counts)}); six tools: {[(n, tools_json[n]['status']) for n in SIX]}; manifest {len(files)} files; observations {len(obs)}")


main()
