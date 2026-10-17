"""Step 8 - the COM timeout path against a real, slow AutoCAD (docs/testing.md: 'not covered live').

AUTOCAD_MCP_COM_TIMEOUT=1.0 makes a normal slow call (autocad_create_new_drawing, 1.6-6 s here) run out of time.
Expected from src/core/com_executor.py: E_COM_TIMEOUT after about 1 s with worker_replaced=true, the abandoned call
may still finish inside AutoCAD, a fresh worker serves the next call, and a call that never started gets E_COM_BUSY.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_harness as h  # noqa: E402
import com_probe as cp  # noqa: E402
from cases import Ctx, acase, case, must, record, short, tool  # noqa: E402


async def run(ctx: Ctx, base):
    d = ctx.data
    n0 = cp.doc_count()

    def chk_caps0(p):
        must(p["config"]["com_timeout_seconds"] == 1.0, p["config"])
        d["stats0"] = p["com_worker"]
    await case(ctx, "TO00", "S", "autocad_get_capabilities", {}, "server runs with AUTOCAD_MCP_COM_TIMEOUT=1.0 and a fresh COM worker", check=chk_caps0)

    t0 = time.perf_counter()

    def chk_timeout(p):
        e = p["error"]
        wall = time.perf_counter() - t0
        must(e["recoverable"] is True and "inspect_the_drawing" in e["recommended_action"], short(e))
        must(e["details"]["worker_replaced"] is True and e["details"]["timeout_seconds"] == 1.0, short(e.get("details")))
        must(0.8 <= wall <= 3.5, f"the error should arrive near the 1 s limit, took {wall:.2f} s")
        d["wall"] = round(wall, 2)
    await case(ctx, "TO01", "S", "autocad_create_new_drawing", {}, "a real AutoCAD call slower than the limit returns E_COM_TIMEOUT near 1 s (worker_replaced=true, advice: inspect before retrying)",
               expect_error="E_COM_TIMEOUT", check=chk_timeout)

    async def still_completes():
        for i in range(60):
            if cp.doc_count() == n0 + 1:
                return f"the abandoned create_new_drawing finished inside AutoCAD about {round(time.perf_counter() - t0, 1)} s after the call (drawing count {n0} -> {n0 + 1}); the error text warned exactly this"
            time.sleep(0.5)
        raise AssertionError(f"no new drawing appeared within 30 s; drawing count stayed {cp.doc_count()}")
    await acase(ctx, "TO02", "S", "autocad_create_new_drawing", "the timed-out call still completes in AutoCAD (E_COM_TIMEOUT's warning is true: exactly one new drawing appears)", still_completes, tool_name="autocad_create_new_drawing", method="real-MCP-stdio+direct-COM")
    time.sleep(3.0)  # let AutoCAD settle

    def chk_list(p):
        mine = cp.doc_list()
        must(p["count"] == len(mine) == n0 + 1, f"{p['count']} vs {len(mine)}")
    await case(ctx, "TO03", "S", "autocad_list_drawings", {}, "after the timeout a fresh worker serves the next call normally (list_drawings equals AutoCAD's own list)", check=chk_list, method="real-MCP-stdio+direct-COM")

    def chk_caps1(p):
        s = p["com_worker"]
        must(s["abandoned_workers"] == 1 and s["worker_generation"] == 2 and s["worker_alive"] is True and s["busy_with"] is None, short(s))  # generation 1 served the timed-out call, generation 2 replaced it
    await case(ctx, "TO04", "S", "autocad_get_capabilities", {}, "com_worker statistics show exactly one abandoned worker and generation 2 (the replacement), idle", check=chk_caps1)

    async def concurrent():
        n_before = cp.doc_count()
        a, b = await asyncio.gather(
            h.call(ctx.session, ctx.log, "autocad_create_new_drawing", {}, label="TO05-a", timeout=60),
            h.call(ctx.session, ctx.log, "autocad_list_drawings", {}, label="TO05-b", timeout=60))
        codes = sorted(filter(None, [h.error_code(a), h.error_code(b)]))
        must(codes == ["E_COM_BUSY", "E_COM_TIMEOUT"] or codes == ["E_COM_TIMEOUT"] or codes == ["E_COM_BUSY", "E_COM_BUSY", "E_COM_TIMEOUT"],
             f"unexpected outcomes {codes}: {short(a['payload'], 160)} | {short(b['payload'], 160)}")
        busy = [x for x in (a, b) if h.error_code(x) == "E_COM_BUSY"]
        if busy:
            msg = busy[0]["payload"]["error"]["message"]
            must(busy[0]["payload"]["error"]["recoverable"] is True and ("Nothing was sent" in msg or "before it started" in msg or "was not started" in msg), short(busy[0]["payload"]))
        for _ in range(60):
            if cp.doc_count() == n_before + 1:
                break
            time.sleep(0.5)
        return f"two concurrent calls with a 1 s limit gave {codes}; the E_COM_BUSY one says nothing was sent to AutoCAD; the call that reached AutoCAD completed anyway (drawing count {n_before} -> {cp.doc_count()})"
    await acase(ctx, "TO05", "S", "autocad_list_drawings", "two concurrent calls: the one stuck behind the slow call is refused with E_COM_BUSY (it never started), not left hanging", concurrent, tool_name="autocad_list_drawings")
    time.sleep(3.0)


async def main():
    base = cp.baseline()
    print("baseline drawings (never touched):", base)
    async with h.open_session("08_timeout", env=h.server_env("com", {"AUTOCAD_MCP_COM_TIMEOUT": "1.0"})) as (session, log):
        ctx = Ctx(session, log, "08_timeout")
        try:
            await run(ctx, base)
        finally:
            time.sleep(2.0)
            closed = cp.close_new_docs(base)
            print("cleanup closed scratch drawings:", closed)


try:
    asyncio.run(main())
except h.StopRun as exc:
    print("STOPPED:", exc)
    sys.exit(2)
