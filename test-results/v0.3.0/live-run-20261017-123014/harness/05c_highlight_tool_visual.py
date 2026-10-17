"""Step 5c - is the TOOL's temporary highlight visible on AutoCAD's screen? (controlled version of HL02)

Same scratch drawing, same window, pictures only after the picture has stopped changing:
  A0 baseline
  A1 direct COM  entity(HandleToObject).Highlight(True)               (control: does AutoCAD show it?)
  A2 direct COM  Highlight(False)
  A3 direct COM  Highlight(True) then doc.Regen(1)                     (the same two calls the server makes)
  A4 direct COM  Highlight(False) + Regen                              (reset)
  B1 MCP tool    autocad_highlight_entity(handle)                      (temporary)
  B2 MCP tool    autocad_highlight_entity(handle, clear=true)
  B3 MCP tool    autocad_highlight_entity(handle, method=persistent, color=1) no redraw by us
  B4 same, then direct doc.Regen(1)                                    (does a regen make the persistent colour show?)
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_harness as h  # noqa: E402
import com_probe as cp  # noqa: E402
from cases import Ctx, must, record, short, tool  # noqa: E402

SHOTS = h.EVIDENCE / "highlight_tool_visual"
SHOTS.mkdir(parents=True, exist_ok=True)
N = {"i": 0}


def one(name):
    cp.print_window(SHOTS / f"{name}.png")
    return SHOTS / f"{name}.png"


def stable(name, tries=8):
    """Capture until two consecutive pictures differ by < 40 px (AutoCAD finished repainting)."""
    prev = one(f"{name}_t0")
    for i in range(1, tries):
        time.sleep(1.2)
        cur = one(f"{name}_t{i}")
        if cp.image_diff(prev, cur)["changed_pixels"] < 40:
            final = SHOTS / f"{name}.png"
            final.write_bytes(cur.read_bytes())
            return final
        prev = cur
    final = SHOTS / f"{name}.png"
    final.write_bytes(prev.read_bytes())
    return final


def px(a, b, name):
    return cp.image_diff(a, b, SHOTS / f"{name}_diff.png")["changed_pixels"]


async def main():
    base = cp.baseline()
    async with h.open_session("05c_highlight_tool_visual", env=h.server_env("com")) as (session, log):
        ctx = Ctx(session, log, "05c_highlight_tool_visual")
        try:
            o = await tool(ctx, "autocad_create_new_drawing", {"pin": True}, label="setup")
            must(not o["is_error"], short(o["payload"]))
            c = await tool(ctx, "autocad_draw_circle", {"center": [100, 100], "radius": 50}, label="circle")
            must(not c["is_error"], short(c["payload"]))
            hd = c["payload"]["handle"]
            l = await tool(ctx, "autocad_draw_line", {"start_point": [0, 0], "end_point": [200, 0]}, label="line")
            lh = l["payload"]["handle"]
            doc = cp.active_doc()
            cp.retry(lambda: cp.app().ZoomExtents())
            time.sleep(2.5)
            a0 = stable("A0_baseline")

            ent = cp.entity(doc, hd)
            cp.retry(lambda: ent.Highlight(True))
            a1 = stable("A1_direct_highlight_on")
            cp.retry(lambda: ent.Highlight(False))
            a2 = stable("A2_direct_highlight_off")
            ent2 = cp.entity(doc, hd)
            cp.retry(lambda: ent2.Highlight(True))
            cp.retry(lambda: doc.Regen(1))
            a3 = stable("A3_direct_highlight_then_regen")
            cp.retry(lambda: ent2.Highlight(False))
            cp.retry(lambda: doc.Regen(1))
            a4 = stable("A4_reset")

            r1 = await tool(ctx, "autocad_highlight_entity", {"handle": hd}, label="B1")
            must(not r1["is_error"], short(r1["payload"]))
            b1 = stable("B1_tool_temporary_on")
            r2 = await tool(ctx, "autocad_highlight_entity", {"handle": hd, "clear": True}, label="B2")
            b2 = stable("B2_tool_temporary_cleared")
            r3 = await tool(ctx, "autocad_highlight_entity", {"handle": lh, "method": "persistent", "color": 1}, label="B3")
            must(not r3["is_error"], short(r3["payload"]))
            b3 = stable("B3_tool_persistent_no_redraw")
            cp.retry(lambda: doc.Regen(1))
            b4 = stable("B4_persistent_after_our_regen")

            res = {
                "A0->A1 direct Highlight(True) via HandleToObject": px(a0, a1, "a0_a1"),
                "A1->A2 direct Highlight(False)": px(a1, a2, "a1_a2"),
                "A0->A2 after off vs baseline": px(a0, a2, "a0_a2"),
                "A2->A3 direct Highlight(True)+Regen (server's sequence)": px(a2, a3, "a2_a3"),
                "A4->B1 TOOL temporary highlight": px(a4, b1, "a4_b1"),
                "B1->B2 TOOL clear": px(b1, b2, "b1_b2"),
                "A4->B2 after tool clear vs baseline": px(a4, b2, "a4_b2"),
                "B2->B3 TOOL persistent colour, no redraw": px(b2, b3, "b2_b3"),
                "B3->B4 our Regen after the persistent colour": px(b3, b4, "b3_b4"),
            }
            h.dump(h.EVIDENCE / "highlight_tool_visual.json", {"pixels_changed": res, "tool_payloads": {"B1": r1["payload"], "B2": r2["payload"], "B3": r3["payload"]}})
            for k, v in res.items():
                print(f"{k}: {v}")

            control_ok = res["A0->A1 direct Highlight(True) via HandleToObject"] >= 500
            tool_ok = res["A4->B1 TOOL temporary highlight"] >= 500
            clear_ok = res["A4->B2 after tool clear vs baseline"] < 500
            regen_ok = res["A2->A3 direct Highlight(True)+Regen (server's sequence)"] >= 500
            persist_nodraw = res["B2->B3 TOOL persistent colour, no redraw"]
            persist_regen = res["B3->B4 our Regen after the persistent colour"]
            if not control_ok:
                st, ev, pr = "BLOCKED", f"AutoCAD's own Highlight(True) via COM changed only {res['A0->A1 direct Highlight(True) via HandleToObject']} px, so the picture method cannot judge the tool", []
            elif not tool_ok:
                st = "FAIL"
                ev = (f"direct Highlight(True) changed {res['A0->A1 direct Highlight(True) via HandleToObject']} px, Highlight+Regen {res['A2->A3 direct Highlight(True)+Regen (server\'s sequence)']} px, "
                      f"but the tool's temporary highlight changed only {res['A4->B1 TOOL temporary highlight']} px")
                pr = [ev]
            elif not clear_ok:
                st, ev = "FAIL", f"tool highlight visible ({res['A4->B1 TOOL temporary highlight']} px) but clear left {res['A4->B2 after tool clear vs baseline']} px"
                pr = [ev]
            else:
                st = "PASS"
                ev = f"tool temporary highlight changed {res['A4->B1 TOOL temporary highlight']} px, clear restored the picture ({res['A4->B2 after tool clear vs baseline']} px off); control (direct COM) {res['A0->A1 direct Highlight(True) via HandleToObject']} px"
                pr = []
            record(id="HL02", category="F", tool="autocad_highlight_entity", title="temporary highlight is visible on AutoCAD's screen and clear=true removes it (controlled picture comparison, attempt 2)",
                   status=st, method="real-MCP-stdio+direct-COM+window-capture", evidence=ev, problems=pr, notes="pictures in evidence/highlight_tool_visual/; supersedes the first HL02 (its positive control had no redraw)",
                   log_ref=f"{ctx.session_name}.jsonl#{ctx.log.n}")
            print(f"[{st}] HL02 {ev}")
            ev2 = f"persistent colour set by the tool: {persist_nodraw} px changed right after the call (no redraw), {persist_regen} px after a regen"
            st2 = "PASS" if persist_nodraw >= 500 else "FAIL"
            record(id="HL02b", category="F", tool="autocad_highlight_entity", title="persistent highlight is visible on screen right after the call (without the user redrawing)",
                   status=st2, method="real-MCP-stdio+direct-COM+window-capture", evidence=ev2,
                   problems=[] if st2 == "PASS" else [ev2 + "; the colour is stored (read back over COM) but AutoCAD's screen keeps the old colour until a regen"], log_ref=f"{ctx.session_name}.jsonl#{ctx.log.n}")
            print(f"[{st2}] HL02b {ev2}")
        finally:
            closed = cp.close_new_docs(base)
            print("cleanup closed:", closed)


try:
    asyncio.run(main())
except h.StopRun as exc:
    print("STOPPED:", exc)
    sys.exit(2)
