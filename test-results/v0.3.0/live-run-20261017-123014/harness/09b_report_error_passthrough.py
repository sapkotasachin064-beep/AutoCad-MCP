"""Step 9b - in the first 07 run, autocad_save_report answered E_INTERNAL ("ToolError: {... E_DOCUMENT_CHANGED ...}") when the
tool it wraps (takeoff / check) was refused. Reproduce it cleanly: AutoCAD running with NO drawing open, so the wrapped
read tools fail with E_NO_ACTIVE_DOCUMENT. Control: the same wrapped tool called directly gives the typed code.
Read-only; nothing is drawn or written (the report path is never created).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_harness as h  # noqa: E402
import com_probe as cp  # noqa: E402
from cases import Ctx, case, must, observe, record, short, tool  # noqa: E402

RPT = h.WORKSPACE / "reports"


async def main():
    base = cp.baseline()
    must(cp.doc_count() == len(base), "setup")
    async with h.open_session("09b_report_error_passthrough", env=h.server_env("com")) as (session, log):
        ctx = Ctx(session, log, "09b_report_error_passthrough")
        await case(ctx, "RP08a", "M", "autocad_quantity_takeoff", {}, "control: with no drawing open the takeoff itself says E_NO_ACTIVE_DOCUMENT", expect_error="E_NO_ACTIVE_DOCUMENT",
                   check=lambda p: must(cp.doc_count() == len(base), "drawing count changed"), method="real-MCP-stdio+direct-COM")
        await case(ctx, "RP08b", "M", "autocad_check_drawing", {}, "control: with no drawing open check_drawing itself says E_NO_ACTIVE_DOCUMENT", expect_error="E_NO_ACTIVE_DOCUMENT")
        target = RPT / "no-drawing.json"
        out = await tool(ctx, "autocad_save_report", {"report": "takeoff", "path": str(target)}, label="RP08")
        code = h.error_code(out)
        msg = out["payload"]["error"]["message"][:200] if out["is_error"] and isinstance(out["payload"], dict) and "error" in out["payload"] else ""
        problems = []
        if code != "E_NO_ACTIVE_DOCUMENT":
            problems.append(f"autocad_save_report answered {code!r} ({msg!r}) although the wrapped tool's own typed error is E_NO_ACTIVE_DOCUMENT; "
                            f"a client is told to 'report a bug' (recommended_action={out['payload']['error'].get('recommended_action')!r}, recoverable={out['payload']['error'].get('recoverable')})")
        if target.exists():
            problems.append("a report file was written although the tool failed")
        record(id="RP08", category="Q", tool="autocad_save_report", title="save_report passes the wrapped tool's typed error through (E_NO_ACTIVE_DOCUMENT) instead of E_INTERNAL",
               status="FAIL" if problems else "PASS", method="real-MCP-stdio+direct-COM", evidence=short(out["payload"], 300), problems=problems,
               log_ref=f"{ctx.session_name}.jsonl#{ctx.log.n}", ms=out["ms"])
        print(f"[{'FAIL' if problems else 'PASS'}] RP08 save_report with no drawing open -> {code}: {msg}")
        if problems:
            observe("OBS-save-report-error-wrap", "autocad_save_report", "medium",
                    "autocad_save_report calls the decorated autocad_check_drawing / autocad_quantity_takeoff functions; their ToolError is caught by its own wrapper and re-classified as E_INTERNAL (recoverable=false, 'report a bug'). Every typed error of the wrapped tools (E_NO_ACTIVE_DOCUMENT, E_DOCUMENT_CHANGED, E_AUTOCAD_NOT_RUNNING ...) is lost.",
                    short(out["payload"], 500))


try:
    asyncio.run(main())
except h.StopRun as exc:
    print("STOPPED:", exc)
    sys.exit(2)
