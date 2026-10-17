"""Step 1 - start AutoCAD 2024 through the MCP server's own tool (autocad_launch_application) and check it.

Needs the owner's go-ahead (given in chat on 2026-10-17). Refuses to run if acad.exe is already running,
because then the cold-start path could not be tested honestly and somebody's drawings might be open.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_harness as h  # noqa: E402
import com_probe as cp  # noqa: E402
from cases import Ctx, case, acase, mark, must, observe, record, short  # noqa: E402

EV = h.EVIDENCE


async def main():
    pids_before = cp.acad_pids()
    if pids_before:
        print(f"STOP: acad.exe is already running (pids {pids_before}); not starting a second test on somebody's session")
        sys.exit(3)

    async with h.open_session("01_launch", env=h.server_env("com")) as (session, log):
        ctx = Ctx(session, log, "01_launch")
        d = ctx.data

        def chk_status_down(p):
            must(p["backend"] == "com", f"backend {p.get('backend')}")
            must(p["installed"] is True, f"installed {p['installed']}")
            must(p["running"] is False and p["connected"] is False and p["supported"] is False, short(p))
            must(cp.acad_pids() == [], "status call must not start AutoCAD")
        await case(ctx, "LV01", "T", "autocad_get_status", {}, "status while AutoCAD is closed: installed, not running, not connected (and the call does not start it)",
                   check=chk_status_down, method="real-MCP-stdio+direct-COM")

        def chk_not_running(p):
            must(cp.acad_pids() == [], "a drawing tool must not start AutoCAD by itself")
        await case(ctx, "LV02", "T", "autocad_list_drawings", {}, "a drawing tool while AutoCAD is closed fails with E_AUTOCAD_NOT_RUNNING and does not start AutoCAD",
                   expect_error="E_AUTOCAD_NOT_RUNNING", check=chk_not_running, method="real-MCP-stdio+direct-COM")

        t0 = time.perf_counter()

        async def chk_launch(p):
            d["launch_payload"] = p
            must(p["connected"] is True and p["supported"] is True, short(p))
            must(str(p["version"]).startswith("24.3"), f"version {p['version']!r}")
            must(p["release_year"] == 2024, f"release_year {p['release_year']}")
            must(p["verified"] is True and p["state"]["executed"] is True, short(p.get("state")))
            pids = cp.acad_pids()
            must(len(pids) == 1, f"expected exactly one acad.exe, got {pids}")
            d["pid"] = pids[0]
            a = cp.app()
            must(cp.retry(lambda: a.Version) == p["version"], "direct COM Application.Version differs from the tool's version")
            must(bool(cp.retry(lambda: a.Visible)), "AutoCAD window should be visible after launch")
        await case(ctx, "LV10", "T", "autocad_launch_application", {"timeout_seconds": 120},
                   "start AutoCAD 2024 from cold through the tool and wait until COM answers", check=chk_launch,
                   timeout=240, method="real-MCP-stdio+direct-COM")
        d["launch_seconds"] = round(time.perf_counter() - t0, 1)
        print(f"launch took {d['launch_seconds']} s")

        info = cp.acad_info()
        info["acad_pids"] = cp.acad_pids()
        info["documents_at_startup"] = cp.doc_list()
        info["launch_wall_seconds"] = d["launch_seconds"]
        h.dump(EV / "autocad_release.json", info)
        h.dump(EV / "baseline_docs.json", cp.baseline())
        print("RELEASE STRING:", info.get("Application.Version"), "| ACADVER:", info.get("var.ACADVER"), "| docs:", info["documents_at_startup"])

        async def again():
            before_docs = cp.doc_count()
            out = await h.call(session, log, "autocad_launch_application", {"timeout_seconds": 60}, label="LV11", timeout=150)
            p = out["payload"]
            must(not out["is_error"] and p["connected"] is True and p["supported"] is True, short(p))
            must(cp.acad_pids() == [d["pid"]], f"second launch changed the process list: {cp.acad_pids()} vs {d['pid']}")
            must(cp.doc_count() == before_docs, "second launch must not open or close drawings")
            return f"same single acad.exe pid {d['pid']}, document count unchanged ({before_docs}), connected={p['connected']}"
        await acase(ctx, "LV11", "T", "autocad_launch_application", "calling launch again while AutoCAD runs only verifies it (same process, no new drawing)",
                    again, tool_name="autocad_launch_application")

        def chk_status_up(p):
            must(p["connected"] is True and p["supported"] is True and p["running"] is True, short(p))
            must(p["version"] == d["launch_payload"]["version"], f"{p['version']} vs {d['launch_payload']['version']}")
            must(p["release_year"] == 2024, f"release_year {p['release_year']}")
        await case(ctx, "LV12", "T", "autocad_get_status", {}, "status after launch: running, connected, supported, release 2024", check=chk_status_up)

        def chk_caps(p):
            must(p["backend"] == "com" and p["server_version"] == "0.3.0", f"{p['backend']} {p['server_version']}")
            must(len(p["tools"]) == 64, f"{len(p['tools'])} tools")
            com_only = sorted(n for n, t in p["tools"].items() if t["backends"] == ["com"])
            must(len(com_only) == 6, f"com-only tools {com_only}")
            must(p["config"]["com_timeout_seconds"] == 120.0, p["config"])
            d["caps"] = p
        await case(ctx, "LV13", "A", "autocad_get_capabilities", {}, "capabilities on the live backend: 64 tools, 6 com-only, 120 s COM timeout", check=chk_caps)

    survives = cp.acad_pids()
    lib_ok = len(survives) == 1 and survives[0] == d["pid"]
    record(id="LV14", category="T", tool="autocad_launch_application", title="AutoCAD keeps running after the MCP server process that started it has exited",
           status="PASS" if lib_ok else "FAIL", method="direct-COM", evidence=f"acad.exe pids after server exit: {survives} (started as {d['pid']})", problems=[] if lib_ok else ["AutoCAD did not survive the server process"], log_ref="n/a")
    print("LV14", "PASS" if lib_ok else "FAIL", survives)


try:
    asyncio.run(main())
except h.StopRun as exc:
    print("STOPPED:", exc)
    sys.exit(2)
