"""Step 1b - AutoCAD was started by the owner (the tool-started cold start crashed, see 01_launch logs).

Attach through the MCP server (autocad_get_status / autocad_launch_application on an already running AutoCAD),
record the exact release string and the drawings that were open before this campaign touched anything.
Nothing here opens, changes or closes a drawing.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_harness as h  # noqa: E402
import com_probe as cp  # noqa: E402
from cases import Ctx, acase, case, must, record, short  # noqa: E402

EV = h.EVIDENCE


async def main():
    pids = cp.acad_pids()
    must(len(pids) == 1, f"expected exactly one acad.exe, got {pids}")
    docs_before = cp.doc_list()

    info = cp.acad_info()
    info["acad_pids"] = pids
    info["documents_when_campaign_attached"] = docs_before
    info["started_by"] = "the owner, by hand (the server-started cold start crashed: see logs/01_launch.*)"
    h.dump(EV / "autocad_release.json", info)
    h.dump(EV / "baseline_docs.json", cp.baseline())
    print("RELEASE STRING:", info.get("Application.Version"), "| ACADVER:", info.get("var.ACADVER"))
    print("documents already open (owner's / startup, never touched):", docs_before)

    async with h.open_session("01b_attach", env=h.server_env("com")) as (session, log):
        ctx = Ctx(session, log, "01b_attach")
        d = ctx.data

        def chk_status(p):
            must(p["backend"] == "com" and p["installed"] and p["running"] and p["connected"] and p["supported"], short(p))
            must(str(p["version"]).startswith("24.3") and p["release_year"] == 2024, f"{p['version']} {p['release_year']}")
            must(p["version"] == info["Application.Version"], "tool version differs from direct COM Application.Version")
            d["version"] = p["version"]
        await case(ctx, "LV20", "T", "autocad_get_status", {}, "status with AutoCAD running: connected, supported, release 2024, version equals the direct COM Application.Version",
                   check=chk_status, method="real-MCP-stdio+direct-COM")

        async def idem():
            out = await h.call(session, log, "autocad_launch_application", {"timeout_seconds": 60}, label="LV21", timeout=150)
            p = out["payload"]
            must(not out["is_error"] and p["connected"] is True and p["supported"] is True and p["verified"] is True, short(p))
            must(cp.acad_pids() == pids, f"process list changed: {cp.acad_pids()} vs {pids}")
            must(cp.doc_list() == docs_before, f"drawings changed: {cp.doc_list()} vs {docs_before}")
            return f"connected={p['connected']} version={p['version']}; same acad.exe {pids}; the {len(docs_before)} open drawing(s) untouched"
        await acase(ctx, "LV21", "T", "autocad_launch_application", "launch while AutoCAD already runs: only verifies it (same process, drawings untouched)", idem,
                    tool_name="autocad_launch_application")

        def chk_caps(p):
            must(p["backend"] == "com" and p["server_version"] == "0.3.0", f"{p['backend']} {p['server_version']}")
            must(len(p["tools"]) == 64, f"{len(p['tools'])} tools")
            com_only = sorted(n for n, t in p["tools"].items() if t["backends"] == ["com"])
            must(len(com_only) == 6, f"com-only tools {com_only}")
            must(p["config"]["com_timeout_seconds"] == 120.0, p["config"])
            h.dump(EV / "capabilities_com.json", p)
        await case(ctx, "LV22", "A", "autocad_get_capabilities", {}, "capabilities on the live backend: 64 tools, 6 com-only, 120 s COM timeout", check=chk_caps)

        async def listing():
            out = await h.call(session, log, "autocad_list_drawings", {}, label="LV23")
            p = out["payload"]
            must(not out["is_error"], short(p))
            theirs = cp.doc_list()
            must(p["count"] == len(theirs), f"{p['count']} vs {len(theirs)}")
            must({r["name"] for r in p["drawings"]} == {r["name"] for r in theirs}, "names differ")
            return f"{p['count']} drawing(s): {[(r['name'], r['identity'], r['active']) for r in p['drawings']]}"
        await acase(ctx, "LV23", "B", "autocad_list_drawings", "list_drawings matches the drawings AutoCAD itself reports (direct COM)", listing, tool_name="autocad_list_drawings")


try:
    asyncio.run(main())
except h.StopRun as exc:
    print("STOPPED:", exc)
    sys.exit(2)
