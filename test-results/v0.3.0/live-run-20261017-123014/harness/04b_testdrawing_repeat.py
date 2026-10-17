"""Step 3b - TD02 failed once with E_INTERNAL 'AttributeError: AddLine.Handle'. Repeat
autocad_create_test_drawing_with_line N times to see how often (the drawing it makes is closed after every call).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_harness as h  # noqa: E402
import com_probe as cp  # noqa: E402
from cases import Ctx, record, short, tool  # noqa: E402

N = 10
TD = h.WORKSPACE / "test-drawings-repeat"


async def main():
    base = cp.baseline()
    TD.mkdir(parents=True, exist_ok=True)
    async with h.open_session("04b_testdrawing_repeat", env=h.server_env("com")) as (session, log):
        ctx = Ctx(session, log, "04b_testdrawing_repeat")
        results = []
        try:
            for i in range(N):
                files_before = {p.name for p in TD.glob("*.dwg")}
                out = await tool(ctx, "autocad_create_test_drawing_with_line", {"output_dir": str(TD)}, label=f"TD04-{i + 1}")
                files_after = {p.name for p in TD.glob("*.dwg")}
                code = h.error_code(out)
                msg = out["payload"]["error"]["message"] if out["is_error"] and isinstance(out["payload"], dict) and "error" in out["payload"] else ""
                row = {"call": i + 1, "ok": not out["is_error"], "code": code, "message": msg[:160], "ms": out["ms"],
                       "new_files": sorted(files_after - files_before), "docs_open_after": cp.doc_count() - len(base)}
                results.append(row)
                print(row)
                cp.close_new_docs(base)  # leave nothing behind between calls
        finally:
            closed = cp.close_new_docs(base)
            print("cleanup closed:", closed)
        failed = [r for r in results if not r["ok"]]
        left_files_on_failure = [r for r in failed if r["new_files"]]
        h.dump(h.EVIDENCE / "04b_testdrawing_repeat.json", results)
        status = "PASS" if not failed else "FAIL"
        problems = [] if not failed else [f"{len(failed)} of {N} calls failed ({sorted({r['code'] for r in failed})}): {failed[0]['message']}; "
                                         f"{len(left_files_on_failure)} of the failed calls had already saved a DWG and left the drawing open"]
        record(id="TD04", category="B", tool="autocad_create_test_drawing_with_line",
               title=f"{N} consecutive calls all succeed (TD02 failed once with an internal AttributeError)", status=status,
               method="real-MCP-stdio+direct-COM", evidence=f"{N - len(failed)} succeeded, {len(failed)} failed; see evidence/04b_testdrawing_repeat.json",
               problems=problems, log_ref=f"{ctx.session_name}.jsonl#1-{ctx.log.n}")
        print(f"[{status}] TD04", problems[:1])


try:
    asyncio.run(main())
except h.StopRun as exc:
    print("STOPPED:", exc)
    sys.exit(2)
