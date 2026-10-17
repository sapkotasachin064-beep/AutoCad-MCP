"""Step 5d - do the three highlight tools show anything on AutoCAD's screen? (final, controlled version)

Method: pictures of AutoCAD's own window (PrintWindow), taken only after the picture stopped changing, in a scratch
drawing whose view is fixed first (ZoomExtents, Regen, ZoomExtents).  A direct-COM entity.Highlight(True) is the
control that proves the pictures can see a highlight.  A highlight is "visible" when the number of halo-coloured (41,78,150) pixels
in the drawing area rises clearly above the baseline picture.  A persistent colour is "visible" when red pixels appear.
Supersedes the HL02 / HL02b records of 05_highlight.py and 05c (their thresholds / controls were wrong).
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image  # noqa: E402

import mcp_harness as h  # noqa: E402
import com_probe as cp  # noqa: E402
from cases import Ctx, must, record, short, tool  # noqa: E402

SHOTS = h.EVIDENCE / "highlight_visual"
SHOTS.mkdir(parents=True, exist_ok=True)


def pictures(name):
    path = SHOTS / f"{name}.png"
    cp.print_window(path)
    return path


def stable(name, tries=8):
    prev = pictures(f"{name}_t0")
    for i in range(1, tries):
        time.sleep(1.2)
        cur = pictures(f"{name}_t{i}")
        if cp.image_diff(prev, cur)["changed_pixels"] < 40:
            break
        prev = cur
    final = SHOTS / f"{name}.png"
    final.write_bytes(prev.read_bytes() if prev != cur else cur.read_bytes())
    for f in SHOTS.glob(f"{name}_t*.png"):
        f.unlink()
    return final


def count(path, kind):
    full = Image.open(path).convert("RGB")
    img = full.crop((0, 190, full.size[0] - 60, full.size[1] - 42))  # drawing area: below the ribbon, left of the tool strip, above the status bar
    n = 0
    for r, g, b in img.get_flattened_data() if hasattr(img, "get_flattened_data") else img.getdata():
        if kind == "blue" and abs(r - 41) <= 14 and abs(g - 78) <= 14 and abs(b - 150) <= 14:  # AutoCAD's highlight halo is (41, 78, 150)
            n += 1
        elif kind == "red" and r >= 200 and g <= 60 and b <= 60:
            n += 1
    return n


async def main():
    base = cp.baseline()
    async with h.open_session("05d_highlight_visual_all", env=h.server_env("com")) as (session, log):
        ctx = Ctx(session, log, "05d_highlight_visual_all")
        try:
            o = await tool(ctx, "autocad_create_new_drawing", {"pin": True}, label="setup")
            must(not o["is_error"], short(o["payload"]))
            hd = {}
            for key, (name, args) in {"C": ("autocad_draw_circle", {"center": [100, 100], "radius": 50}),
                                      "L": ("autocad_draw_line", {"start_point": [0, 0], "end_point": [200, 0]}),
                                      "T1": ("autocad_draw_text", {"text": "PMC-3M-A1", "insertion_point": [10, 190], "height": 10}),
                                      "T2": ("autocad_draw_text", {"text": "OTHER", "insertion_point": [10, 215], "height": 10})}.items():
                r = await tool(ctx, name, args, label=f"setup-{key}")
                must(not r["is_error"], short(r["payload"]))
                hd[key] = r["payload"]["handle"]
            doc = cp.active_doc()
            app = cp.app()
            cp.retry(lambda: app.ZoomExtents())
            cp.retry(lambda: doc.Regen(1))
            cp.retry(lambda: app.ZoomExtents())
            time.sleep(2.0)
            m = {}

            def snap(key, name):
                p = stable(name)
                m[key] = {"file": p.name, "blue": count(p, "blue"), "red": count(p, "red")}
                print(f"{key:44s} blue={m[key]['blue']:6d} red={m[key]['red']:6d}")
                return p

            snap("baseline", "V0_baseline")
            ent = cp.entity(doc, hd["C"])
            cp.retry(lambda: ent.Highlight(True))
            snap("control: direct Highlight(True)", "V1_direct_on")
            cp.retry(lambda: ent.Highlight(False))
            snap("control: direct Highlight(False)", "V2_direct_off")
            cp.retry(lambda: ent.Highlight(True))
            cp.retry(lambda: doc.Regen(1))
            snap("direct Highlight(True) then doc.Regen(1)", "V3_direct_on_regen")
            cp.retry(lambda: ent.Highlight(False))
            cp.retry(lambda: doc.Regen(1))
            snap("reset", "V4_reset")

            t1 = await tool(ctx, "autocad_highlight_entity", {"handle": hd["C"]}, label="V-tool-entity")
            snap("TOOL highlight_entity temporary", "V5_tool_entity")
            await tool(ctx, "autocad_highlight_entity", {"handle": hd["C"], "clear": True}, label="V-tool-entity-clear")
            snap("TOOL highlight_entity clear", "V6_tool_entity_clear")

            t2 = await tool(ctx, "autocad_highlight_text_matches", {"pattern": "PMC"}, label="V-tool-text")
            snap("TOOL highlight_text_matches temporary", "V7_tool_text")
            await tool(ctx, "autocad_highlight_text_matches", {"pattern": "PMC", "clear": True}, label="V-tool-text-clear")
            snap("TOOL highlight_text_matches clear", "V8_tool_text_clear")

            sc = await tool(ctx, "autocad_scan_all_entities", {}, label="V-scan")
            t3 = await tool(ctx, "autocad_query_and_highlight", {"query": "SELECT handle FROM entities WHERE object_name = ?", "params": ["AcDbCircle"]}, label="V-tool-query")
            snap("TOOL query_and_highlight temporary", "V9_tool_query")
            await tool(ctx, "autocad_query_and_highlight", {"query": "SELECT handle FROM entities WHERE object_name = ?", "params": ["AcDbCircle"], "clear": True}, label="V-tool-query-clear")
            snap("TOOL query_and_highlight clear", "V10_tool_query_clear")

            t4 = await tool(ctx, "autocad_highlight_entity", {"handle": hd["L"], "method": "persistent", "color": 1}, label="V-tool-persistent")
            snap("TOOL highlight_entity persistent colour 1", "V11_tool_persistent")
            cp.retry(lambda: doc.Regen(1))
            snap("same, after a regen by the harness", "V12_persistent_after_regen")

            h.dump(h.EVIDENCE / "highlight_visual.json", {"counts": m, "payloads": {"entity": t1["payload"], "text": t2["payload"], "query": t3["payload"], "persistent": t4["payload"]}})

            base_blue = m["baseline"]["blue"]
            control = m["control: direct Highlight(True)"]["blue"] - base_blue
            after_regen = m["direct Highlight(True) then doc.Regen(1)"]["blue"] - base_blue
            print(f"control +{control} blue px; direct highlight followed by Regen +{after_regen} blue px")

            def verdict(cid, tool_name, title, key, clear_key):
                gain = m[key]["blue"] - m["reset"]["blue"]
                if control < 150:
                    st, ev, pr = "BLOCKED", f"the picture method could not see AutoCAD's own highlight (control +{control} blue px), so the tool cannot be judged", []
                elif gain >= 150:
                    left = m[clear_key]["blue"] - m["reset"]["blue"]
                    if left <= 60:
                        st, ev, pr = "PASS", f"highlight visible on screen (+{gain} blue px; AutoCAD's own highlight gave +{control}); clear removed it ({left} px left)", []
                    else:
                        st, ev = "FAIL", f"visible (+{gain} blue px) but {left} blue px remained after clear"
                        pr = [ev]
                else:
                    st = "FAIL"
                    ev = (f"the tool reported success but nothing is highlighted on AutoCAD's screen: +{gain} blue px after the call "
                          f"(a direct Highlight(True) gives +{control}; Highlight(True) followed by doc.Regen(1) -- the tool's own sequence -- gives +{after_regen})")
                    pr = [ev]
                record(id=cid, category="F", tool=tool_name, title=title, status=st, method="real-MCP-stdio+direct-COM+window-capture", evidence=ev, problems=pr,
                       notes="pictures in evidence/highlight_visual/, numbers in evidence/highlight_visual.json; supersedes earlier records with this id",
                       log_ref=f"{ctx.session_name}.jsonl#{ctx.log.n}")
                print(f"[{st}] {cid} {ev}")

            verdict("HL02", "autocad_highlight_entity", "temporary highlight is visible on AutoCAD's screen and clear=true removes it (pictures, final)", "TOOL highlight_entity temporary", "TOOL highlight_entity clear")
            verdict("HL19", "autocad_highlight_text_matches", "temporary text highlight is visible on AutoCAD's screen and clear removes it (pictures)", "TOOL highlight_text_matches temporary", "TOOL highlight_text_matches clear")
            verdict("HL29", "autocad_query_and_highlight", "temporary query highlight is visible on AutoCAD's screen and clear removes it (pictures)", "TOOL query_and_highlight temporary", "TOOL query_and_highlight clear")

            red_gain = m["TOOL highlight_entity persistent colour 1"]["red"] - m["TOOL query_and_highlight clear"]["red"]
            red_regen = m["same, after a regen by the harness"]["red"] - m["TOOL query_and_highlight clear"]["red"]
            st = "PASS" if red_gain >= 100 else "FAIL"
            ev = (f"after the persistent highlight call, +{red_gain} red pixels appeared on AutoCAD's screen without any redraw by the harness; "
                  f"after a regen by the harness +{red_regen} red pixels (the colour IS stored, it is only repainted on the next redraw)")
            record(id="HL02b", category="F", tool="autocad_highlight_entity", title="persistent highlight colour is visible on AutoCAD's screen right after the call (red pixels appear)", status=st,
                   method="real-MCP-stdio+direct-COM+window-capture", evidence=ev, problems=[] if st == "PASS" else [ev], log_ref=f"{ctx.session_name}.jsonl#{ctx.log.n}")
            print(f"[{st}] HL02b {ev}")
        finally:
            closed = cp.close_new_docs(base)
            print("cleanup closed:", closed)


try:
    asyncio.run(main())
except h.StopRun as exc:
    print("STOPPED:", exc)
    sys.exit(2)
