"""Step 5 - autocad_highlight_entity, autocad_highlight_text_matches, autocad_query_and_highlight on a real AutoCAD.

Colours are read back with direct COM. The temporary (display-only) highlight cannot be read back over COM, so
window screenshots (PrintWindow + screen grab of AutoCAD's own window) are compared before / after, with a
persistent colour change as the positive control that proves the capture can see changes at all.
"""

import asyncio
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_harness as h  # noqa: E402
import com_probe as cp  # noqa: E402
from cases import Ctx, acase, case, must, observe, record, short, tool  # noqa: E402

EV = h.EVIDENCE
SHOTS = EV / "highlight"
SHOTS.mkdir(parents=True, exist_ok=True)


def color_of(handle):
    return cp.describe(cp.entity(cp.active_doc(), handle))["color"]


def text_of(handle):
    return cp.describe(cp.entity(cp.active_doc(), handle))["text"]


def reset_colors(handles):
    doc = cp.active_doc()
    for hd in handles:
        cp.retry(lambda hd=hd: setattr(cp.entity(doc, hd), "Color", 256))


def shot(name):
    """Two pictures of AutoCAD's window (PrintWindow and a screen grab) after letting it repaint."""
    time.sleep(2.0)
    pw = cp.print_window(SHOTS / f"{name}_printwindow.png")
    gr = cp.capture_window(SHOTS / f"{name}_grab.png", bring_to_front=False)
    return {"printwindow": SHOTS / f"{name}_printwindow.png", "grab": SHOTS / f"{name}_grab.png", "pw": pw, "gr": gr}


def diff(a, b, name):
    out = {}
    for kind in ("printwindow", "grab"):
        out[kind] = cp.image_diff(a[kind], b[kind], SHOTS / f"{name}_{kind}_diff.png")
    return out


async def run(ctx: Ctx, base):
    d = ctx.data
    out = await tool(ctx, "autocad_create_new_drawing", {"pin": True}, label="setup")
    must(not out["is_error"], short(out["payload"]))
    d["drawing"] = out["payload"]["drawing_name"]

    async def draw(name, args, label):
        o = await tool(ctx, name, args, label=label)
        must(not o["is_error"], f"{label}: {short(o['payload'])}")
        return o["payload"]["handle"]

    hd = {}
    hd["L1"] = await draw("autocad_draw_line", {"start_point": [0, 0], "end_point": [200, 0]}, "L1")
    hd["L2"] = await draw("autocad_draw_line", {"start_point": [0, 50], "end_point": [200, 50]}, "L2")
    hd["C1"] = await draw("autocad_draw_circle", {"center": [100, 150], "radius": 40, "layer": "MCP_H"}, "C1")
    hd["T1"] = await draw("autocad_draw_text", {"text": "PMC-3M-A101", "insertion_point": [0, 250], "height": 10}, "T1")
    hd["T2"] = await draw("autocad_draw_text", {"text": "PMC-3M-A102", "insertion_point": [0, 280], "height": 10}, "T2")
    hd["T3"] = await draw("autocad_draw_text", {"text": "PMC-3M-B7", "insertion_point": [0, 310], "height": 10}, "T3")
    hd["T4"] = await draw("autocad_draw_text", {"text": "OTHER-77", "insertion_point": [0, 340], "height": 10}, "T4")
    hd["M1"] = await draw("autocad_draw_mtext", {"text": r"Room: PMC-3M-A103\P12 m2", "insertion_point": [150, 250], "height": 10, "width": 120}, "M1")
    d["h"] = hd
    original_texts = {k: text_of(v) for k, v in hd.items() if k.startswith(("T", "M"))}
    print("handles:", hd, "| texts:", original_texts)
    cp.retry(lambda: cp.app().ZoomExtents())

    # ------------------------------------------------------------------ highlight_entity: temporary
    def chk_temp(p):
        must(p["highlighted"] is True and p["method"] == "temporary", short(p))
        must(p["color"] == color_of(hd["C1"]) == 256, f"reported colour {p['color']} vs direct COM {color_of(hd['C1'])}")
        must(p["verified"] is False and str(p["verification"]).startswith("not_verifiable"), "the tool must say it cannot verify a display-only state")
        must(p["state"]["executed"] is True and p["state"]["verified"] is False, short(p["state"]))
    s0 = shot("hl_0_before")
    await case(ctx, "HL01", "F", "autocad_highlight_entity", {"handle": hd["C1"]}, "temporary highlight: accepted, colour untouched (direct COM), and honestly reports verified=false (state is not readable over COM)",
               check=chk_temp, method="real-MCP-stdio+direct-COM")
    s1 = shot("hl_1_temp_on")

    async def visual_temp():
        dd = diff(s0, s1, "hl_0_vs_1")
        h.dump(SHOTS / "hl_0_vs_1_diff.json", dd)
        seen = {k: v.get("changed_pixels") for k, v in dd.items()}
        return seen
    seen = await visual_temp()
    print("pixels changed by the temporary highlight:", seen)

    await case(ctx, "HL03", "F", "autocad_highlight_entity", {"handle": hd["C1"], "clear": True}, "clear=true switches the temporary highlight off",
               check=lambda p: must(p["highlighted"] is False and color_of(hd["C1"]) == 256, short(p)), method="real-MCP-stdio+direct-COM")
    s2 = shot("hl_2_temp_cleared")
    d12 = diff(s1, s2, "hl_1_vs_2")
    d02 = diff(s0, s2, "hl_0_vs_2")
    print("pixels changed by clearing:", {k: v.get("changed_pixels") for k, v in d12.items()}, "| after clear vs original:", {k: v.get("changed_pixels") for k, v in d02.items()})

    # positive control: a persistent colour change must be visible to the same capture
    await case(ctx, "HL04", "F", "autocad_highlight_entity", {"handle": hd["L1"], "method": "persistent", "color": 1}, "persistent highlight sets the colour (read back: 1) and reports the original (256)",
               check=lambda p: must(p["verified"] is True and p["color"] == 1 and p["original_color"] == 256 and color_of(hd["L1"]) == 1, short(p)), method="real-MCP-stdio+direct-COM")
    s3 = shot("hl_3_persistent_control")
    d03 = diff(s0, s3, "hl_0_vs_3")
    print("positive control (persistent colour) changed pixels:", {k: v.get("changed_pixels") for k, v in d03.items()})
    reset_colors([hd["L1"]])

    def visible(dd):
        return max((v.get("changed_pixels") or 0) for v in dd.values())

    control_px, temp_px, back_px = visible(d03), visible(diff(s0, s1, "hl_0_vs_1_again")), visible(d02)
    problems = []
    if control_px < 50:
        status, ev = "BLOCKED", f"the screenshot method could not even see a persistent colour change ({control_px} px); the temporary highlight cannot be judged visually"
    elif temp_px < 50:
        status, ev = "FAIL", f"persistent colour change changed {control_px} px (capture works), temporary highlight changed only {temp_px} px: no visible highlight after the tool call"
        problems.append(ev)
    elif back_px > 25:
        status, ev = "FAIL", f"highlight visible ({temp_px} px) but clearing left {back_px} px different from the original picture"
        problems.append(ev)
    else:
        status, ev = "PASS", f"temporary highlight changed {temp_px} px of AutoCAD's window; clearing returned to the original ({back_px} px off); positive control (persistent colour) {control_px} px"
    record(id="HL02", category="F", tool="autocad_highlight_entity", title="temporary highlight is visible on AutoCAD's screen and clear=true removes it (window pictures compared before / on / after)",
           status=status, method="real-MCP-stdio+window-capture", evidence=ev, problems=problems, notes="pictures in evidence/highlight/", log_ref=f"{ctx.session_name}.jsonl#{ctx.log.n}")
    print(f"[{status}] HL02 {ev}")

    # ------------------------------------------------------------------ highlight_entity: persistent / refusals
    await case(ctx, "HL05", "F", "autocad_highlight_entity", {"handle": hd["L2"], "method": "persistent", "color": 4}, "persistent highlight colour 4 on another line",
               check=lambda p: must(p["verified"] is True and color_of(hd["L2"]) == 4 and color_of(hd["L1"]) == 256, short(p)), method="real-MCP-stdio+direct-COM")
    reset_colors([hd["L2"]])
    await case(ctx, "HL06", "F", "autocad_highlight_entity", {"handle": "FFFFF"}, "a well-formed but non-existent handle -> E_ENTITY_NOT_FOUND", expect_error="E_ENTITY_NOT_FOUND")
    await case(ctx, "HL07", "F", "autocad_highlight_entity", {"handle": "not a handle!"}, "a malformed handle -> E_INVALID_INPUT", expect_error="E_INVALID_INPUT")
    await case(ctx, "HL08", "F", "autocad_highlight_entity", {"handle": hd["C1"], "method": "blink"}, "unknown method -> E_INVALID_INPUT", expect_error="E_INVALID_INPUT")
    await case(ctx, "HL09", "F", "autocad_highlight_entity", {"handle": hd["C1"], "method": "persistent", "color": 999}, "persistent colour 999 -> E_INVALID_INPUT and the entity keeps its colour",
               expect_error="E_INVALID_INPUT", check=lambda p: must(color_of(hd["C1"]) == 256, "colour changed by a refused call"), method="real-MCP-stdio+direct-COM")

    # ------------------------------------------------------------------ highlight_text_matches
    texts_ok = lambda: must({k: text_of(v) for k, v in hd.items() if k.startswith(("T", "M"))} == original_texts, "a text entity's content changed")

    def chk_lit(p):
        got = {m["handle"] for m in p["matches"]}
        must(p["match_count"] == 4 and got == {hd["T1"], hd["T2"], hd["T3"], hd["M1"]}, f"matches {sorted(got)} count {p['match_count']}")
        must(all(m["highlighted"] is True for m in p["matches"]) and p["truncated"] is False, short(p))
        texts_ok()
        must(color_of(hd["T4"]) == 256 and all(color_of(hd[k]) == 256 for k in ("T1", "T2", "T3", "M1")), "temporary highlight must not change any colour")
    await case(ctx, "HL10", "F", "autocad_highlight_text_matches", {"pattern": "PMC-3M"}, "literal 'PMC-3M': exactly the 3 TEXT + 1 MTEXT entities, text content unchanged, colours untouched (direct COM)", check=chk_lit, method="real-MCP-stdio+direct-COM")

    def chk_re(p):
        got = {m["handle"] for m in p["matches"]}
        must(p["match_count"] == 3 and got == {hd["T1"], hd["T2"], hd["M1"]}, f"matches {sorted(got)}")
    await case(ctx, "HL11", "F", "autocad_highlight_text_matches", {"pattern": r"PMC-3M-A\d+", "use_regex": True}, "regex PMC-3M-A\\d+ matches the 2 TEXT + the MTEXT, not PMC-3M-B7", check=chk_re)

    def chk_limit(p):
        must(p["match_count"] == 4 and len(p["matches"]) == 2 and p["truncated"] is True, short({k: p[k] for k in ("match_count", "truncated")}))
    await case(ctx, "HL12", "F", "autocad_highlight_text_matches", {"pattern": "PMC-3M", "limit": 2}, "limit=2: match_count stays 4, only 2 listed, truncated=true", check=chk_limit)
    await case(ctx, "HL13", "F", "autocad_highlight_text_matches", {"pattern": "PMC-3M", "clear": True}, "clear=true reports highlighted=false for every match",
               check=lambda p: must(p["match_count"] == 4 and all(m["highlighted"] is False for m in p["matches"]), short(p)))

    def chk_persist(p):
        got = {m["handle"]: m for m in p["matches"]}
        must(set(got) == {hd["T1"], hd["T2"], hd["M1"]}, f"{sorted(got)}")
        must(all(m["original_color"] == 256 and m["color"] == 2 for m in got.values()), short(p))
        must(all(color_of(hd[k]) == 2 for k in ("T1", "T2", "M1")), "direct COM: matched entities should be colour 2")
        must(color_of(hd["T3"]) == 256 and color_of(hd["T4"]) == 256, "non-matching entities must keep their colour")
        texts_ok()
    await case(ctx, "HL14", "F", "autocad_highlight_text_matches", {"pattern": "PMC-3M-A", "method": "persistent", "color": 2}, "persistent colour 2 on 'PMC-3M-A': 3 matches recoloured (direct COM), others and all text content untouched", check=chk_persist, method="real-MCP-stdio+direct-COM")
    reset_colors([hd["T1"], hd["T2"], hd["M1"]])
    await case(ctx, "HL15", "F", "autocad_highlight_text_matches", {"pattern": ""}, "empty literal pattern -> E_INVALID_INPUT", expect_error="E_INVALID_INPUT")
    await case(ctx, "HL16", "F", "autocad_highlight_text_matches", {"pattern": "(", "use_regex": True}, "invalid regex -> E_INVALID_INPUT", expect_error="E_INVALID_INPUT")
    await case(ctx, "HL17", "F", "autocad_highlight_text_matches", {"pattern": "NO-SUCH-TEXT"}, "no match -> ok with match_count 0", check=lambda p: must(p["match_count"] == 0 and p["matches"] == [], short(p)))
    await case(ctx, "HL18", "F", "autocad_highlight_text_matches", {"pattern": "pmc-3m"}, "matching is case-sensitive (lower-case pattern finds nothing)", check=lambda p: must(p["match_count"] == 0, short(p)))

    # ------------------------------------------------------------------ query_and_highlight
    def chk_scan(p):
        mine = cp.model_counts(cp.active_doc())
        must(p["scanned_count"] == mine["total"] == 8, f"scanned {p['scanned_count']} vs COM {mine['total']}")
        must(p["entity_type_counts"] == mine["by_type"], f"{p['entity_type_counts']} vs {mine['by_type']}")
        d["db_path"] = p["db_path"]
        d["identity"] = p["drawing_identity"]
        con = sqlite3.connect(Path(p["db_path"]).as_uri() + "?mode=ro", uri=True)
        try:
            rows = con.execute("SELECT e.handle FROM entities e JOIN drawings d ON d.id = e.drawing_id WHERE d.identity = ?", (p["drawing_identity"],)).fetchall()
        finally:
            con.close()
        must(sorted(r[0] for r in rows) == sorted(hd.values()), f"database rows {sorted(r[0] for r in rows)} vs drawn handles {sorted(hd.values())}")
    await case(ctx, "HL20", "F", "autocad_scan_all_entities", {}, "scan: 8 entities counted by type like AutoCAD does, and the SQLite file (read independently) holds exactly those handles", check=chk_scan, method="real-MCP-stdio+direct-COM+file")

    def chk_qh_temp(p):
        must(p["method"] == "temporary" and p["row_count"] == 2 and sorted(p["highlighted_handles"]) == sorted([hd["L1"], hd["L2"]]) and p["not_found"] == [], short(p))
        must(color_of(hd["L1"]) == 256, "temporary highlight must not recolour")
    await case(ctx, "HL21", "F", "autocad_query_and_highlight", {"query": "SELECT handle FROM entities WHERE object_name = ?", "params": ["AcDbLine"]}, "query for lines, temporary highlight: both line handles highlighted, none missing, colours untouched", check=chk_qh_temp, method="real-MCP-stdio+direct-COM")

    def chk_qh_persist(p):
        must(p["highlighted_handles"] == [hd["C1"]] and p["color"] == 6, short(p))
        must(color_of(hd["C1"]) == 6 and all(color_of(hd[k]) == 256 for k in ("L1", "L2", "T1")), "only the circle should be recoloured")
    await case(ctx, "HL22", "F", "autocad_query_and_highlight", {"query": "SELECT handle FROM entities WHERE layer = ?", "params": ["MCP_H"], "method": "persistent", "color": 6}, "query on layer MCP_H, persistent colour 6: only the circle changes (direct COM)", check=chk_qh_persist, method="real-MCP-stdio+direct-COM")
    reset_colors([hd["C1"]])

    # stale handle: delete L2 in AutoCAD after the scan
    del_ = await tool(ctx, "autocad_delete_entities", {"handles": [hd["L2"]], "dry_run": False}, label="HL23-setup-delete")
    must(not del_["is_error"], short(del_["payload"]))

    def chk_stale(p):
        must(p["not_found"] == [hd["L2"]] and p["highlighted_handles"] == [hd["L1"]] and p["highlighted_count"] == 1, short(p))
    await case(ctx, "HL23", "F", "autocad_query_and_highlight", {"query": "SELECT handle FROM entities WHERE object_name = ?", "params": ["AcDbLine"]}, "a stale handle (entity deleted after the scan) is reported in not_found, the rest is highlighted, nothing is raised", check=chk_stale)
    await case(ctx, "HL24", "F", "autocad_query_and_highlight", {"query": "SELECT object_name FROM entities"}, "a query without a handle column -> E_INVALID_INPUT", expect_error="E_INVALID_INPUT")
    await case(ctx, "HL25", "F", "autocad_query_and_highlight", {"query": "DELETE FROM entities"}, "a write statement is rejected (E_QUERY_REJECTED)", expect_error="E_QUERY_REJECTED")
    await case(ctx, "HL26", "F", "autocad_query_and_highlight", {"query": "SELECT handle FROM entities; DROP TABLE entities"}, "two statements are rejected (E_QUERY_REJECTED)", expect_error="E_QUERY_REJECTED")
    await case(ctx, "HL27", "F", "autocad_query_and_highlight", {"query": "SELECT handle FROM entities WHERE 1 = 0"}, "a query with no rows highlights nothing and says so", check=lambda p: must(p["highlighted_count"] == 0 and p["not_found"] == [], short(p)))
    await case(ctx, "HL28", "F", "autocad_query_and_highlight", {"query": "SELECT handle FROM entities WHERE object_name = ?", "params": ["AcDbText"], "clear": True}, "clear=true with a query highlights none visually but reports the handles processed",
               check=lambda p: must(sorted(p["highlighted_handles"]) == sorted([hd["T1"], hd["T2"], hd["T3"], hd["T4"]]), short(p)))

    # ------------------------------------------------------------------ cross-drawing scope (an observation, not a pass/fail)
    async def cross_drawing():
        c1_handle_in_a = hd["C1"]
        new = await tool(ctx, "autocad_create_new_drawing", {"pin": True}, label="HL30-setup-B")
        must(not new["is_error"], short(new["payload"]))
        b = {}
        for key, (name, args) in {"L1": ("autocad_draw_line", {"start_point": [0, 0], "end_point": [200, 0]}),
                                  "L2": ("autocad_draw_line", {"start_point": [0, 50], "end_point": [200, 50]}),
                                  "C1": ("autocad_draw_circle", {"center": [100, 150], "radius": 40, "layer": "MCP_OTHER"})}.items():
            o = await tool(ctx, name, args, label=f"HL30-B-{key}")
            must(not o["is_error"], short(o["payload"]))
            b[key] = o["payload"]["handle"]
        same_handle = {k: (b[k], hd[k]) for k in b if b[k] == hd[k]}
        res = await tool(ctx, "autocad_query_and_highlight", {"query": "SELECT handle FROM entities WHERE layer = ?", "params": ["MCP_H"], "method": "persistent", "color": 6}, label="HL30-query")
        recoloured = {k: color_of(v) for k, v in b.items()}
        info = {"handles_in_drawing_A": hd, "handles_in_drawing_B": b, "identical_handles": same_handle, "query_result": res["payload"] if not res["is_error"] else short(res["payload"]), "colours_in_B_after": recoloured}
        h.dump(EV / "highlight_cross_drawing.json", info)
        if not res["is_error"] and recoloured["C1"] == 6 and b["C1"] == c1_handle_in_a:
            observe("OBS-query-highlight-scope", "autocad_query_and_highlight", "medium",
                    "query_and_highlight is not scoped to the active drawing: a scan row of drawing A (layer MCP_H) coloured an unrelated circle on layer MCP_OTHER in drawing B because both drawings give the same handle.",
                    short(info, 700))
            return f"REPRODUCED: handles collide ({same_handle}); drawing B circle on MCP_OTHER was recoloured to 6 by a query about layer MCP_H of drawing A"
        return f"not reproduced with these drawings: identical handles {same_handle}, B colours {recoloured}, result {short(info['query_result'], 200)}"
    ok = await acase(ctx, "HL30", "F", "autocad_query_and_highlight", "observation: scan rows of drawing A used while drawing B is active (handle collision between drawings)", cross_drawing, tool_name="autocad_query_and_highlight")


async def main():
    base = cp.baseline()
    print("baseline drawings (never touched):", base)
    async with h.open_session("05_highlight", env=h.server_env("com")) as (session, log):
        ctx = Ctx(session, log, "05_highlight")
        try:
            await run(ctx, base)
        finally:
            closed = cp.close_new_docs(base)
            print("cleanup closed scratch drawings:", closed)


try:
    asyncio.run(main())
except h.StopRun as exc:
    print("STOPPED:", exc)
    sys.exit(2)
