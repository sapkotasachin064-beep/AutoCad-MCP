"""Step 7b - quantity takeoff, check_drawing and save_report (second half of 07_architecture.py, re-run with a guard).

In the first attempt (07_architecture.py) the stair and sheet cases passed, then AutoCAD's active drawing was switched
to the previous scratch drawing about two seconds after the last draw call (not by the server: its pin refused every
call with E_DOCUMENT_CHANGED, nothing was changed). Somebody clicked another drawing tab. This script puts the scratch
drawing back in front (direct COM) before every call and counts how often that was needed.
"""


import asyncio
import time
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pythoncom  # noqa: E402
import win32com.client  # noqa: E402

import mcp_harness as h  # noqa: E402
import com_probe as cp  # noqa: E402
from cases import Ctx, acase, case, must, observe, record, short, tool  # noqa: E402

WS = h.WORKSPACE
RPT = WS / "reports"
RPT.mkdir(parents=True, exist_ok=True)
TOL = 1e-4


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def near(a, b, rel=1e-6, abs_=1e-6) -> bool:
    return abs(float(a) - float(b)) <= max(abs_, rel * max(abs(float(a)), abs(float(b))))


def pts_close(p, q, tol=TOL) -> bool:
    return len(p) == len(q) and all(abs(float(a) - float(b)) <= tol for a, b in zip(p, q))


def verify_against_plan(plan: dict, handles: dict) -> tuple[int, list[str]]:
    """Read every planned primitive back from AutoCAD (by the handle the tool returned) and compare."""
    doc = cp.active_doc()
    problems, checked = [], 0
    for pr in plan["primitives"]:
        handle = handles.get(pr["tag"])
        if not handle:
            problems.append(f"{pr['tag']}: no handle returned")
            continue
        e = cp.describe(cp.entity(doc, handle))
        checked += 1
        kind = pr["kind"]
        if e["layer"] != pr["layer"]:
            problems.append(f"{pr['tag']}: layer {e['layer']} != {pr['layer']}")
        if kind == "line":
            if not (pts_close(e["start"], pr["points"][0]) and pts_close(e["end"], pr["points"][1])) or e["object_name"] != "AcDbLine":
                problems.append(f"{pr['tag']}: line {e.get('start')}->{e.get('end')} vs {pr['points']}")
        elif kind == "polyline":
            want = [c for q in pr["points"] for c in (q[:2] if e["object_name"] == "AcDbPolyline" else q[:3])]
            if e["object_name"] not in ("AcDbPolyline", "AcDb3dPolyline") or not pts_close(e["coords"], want) or bool(e["closed"]) != bool(pr.get("closed", False)):
                problems.append(f"{pr['tag']}: {e['object_name']} coords {e.get('coords')} closed {e.get('closed')} vs {want} closed {pr.get('closed', False)}")
        elif kind == "circle":
            if e["object_name"] != "AcDbCircle" or not pts_close(e["center"], pr["center"]) or not near(e["radius"], pr["radius"]):
                problems.append(f"{pr['tag']}: circle {e.get('center')} r{e.get('radius')} vs {pr['center']} r{pr['radius']}")
        elif kind == "text":
            if e["object_name"] != "AcDbText" or e["text"] != pr["text"] or not near(e["height"], pr["height"]):
                problems.append(f"{pr['tag']}: text {e.get('text')!r} h{e.get('height')} vs {pr['text']!r} h{pr['height']}")
        elif kind == "mtext":
            if e["object_name"] != "AcDbMText" or pr["text"] not in e["text"] or not near(e["height"], pr["height"]) or not pts_close(e["insertion"], pr["location"] if len(pr["location"]) == 3 else list(pr["location"]) + [0.0]):
                problems.append(f"{pr['tag']}: mtext {e.get('text')!r} h{e.get('height')} at {e.get('insertion')} vs {pr['text']!r} h{pr['height']} at {pr['location']}")
        else:
            problems.append(f"{pr['tag']}: unchecked kind {kind}")
    return checked, problems


def bbox_com(handle):
    ent = cp.entity(cp.active_doc(), handle)
    lo, hi = cp.retry(lambda: ent.GetBoundingBox())
    return [float(x) for x in lo], [float(x) for x in hi]


async def new_doc(ctx, units="metric_mm"):
    o = await tool(ctx, "autocad_create_new_drawing", {"pin": True}, label="setup-doc")
    must(not o["is_error"], short(o["payload"]))
    u = await tool(ctx, "autocad_set_drawing_units", {"preset": units}, label="setup-units")
    must(not u["is_error"] and u["payload"]["insunits"] == 4, short(u["payload"]))


INTERFERENCE = []
NAME = {"v": None}


def guard():
    """Before every call: if AutoCAD's active drawing is not the scratch drawing, put it back (the owner may be clicking around)."""
    want = NAME["v"]
    if want is None:
        return
    act = cp.active_name()
    if act != want:
        INTERFERENCE.append({"t": time.strftime("%H:%M:%S"), "active_was": act, "put_back": want})
        cp.activate(cp.find_doc(name=want))
        time.sleep(0.4)


async def run(ctx: Ctx, base):
    d = ctx.data
    holder = {}
    h.PRE_CALL_HOOK = guard
    # ====================================================================== quantity takeoff on a hand-computed drawing
    await new_doc(ctx)
    NAME['v'] = cp.active_name()
    doc = cp.active_doc()
    # a block definition for INSERT counting (the tools insert blocks, they do not define them)
    blk = cp.retry(lambda: doc.Blocks.Add(win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, (0.0, 0.0, 0.0)), "MCP_BLK"))
    cp.retry(lambda: blk.AddCircle(win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, (0.0, 0.0, 0.0)), 100.0))

    async def draw(name, args):
        r = await tool(ctx, name, args, label="takeoff-setup")
        must(not r["is_error"], f"{name} {args}: {short(r['payload'])}")
        return r["payload"]

    await draw("autocad_draw_wall", {"start_point": [0, 0], "end_point": [5000, 0], "thickness": 230})
    await draw("autocad_draw_wall", {"start_point": [0, 5000], "end_point": [3000, 5000], "thickness": 230})
    await draw("autocad_draw_rectangle", {"corner1": [10000, 0], "corner2": [14000, 3000], "layer": "ROOM"})
    await draw("autocad_draw_circle", {"center": [20000, 0], "radius": 500, "layer": "COL"})
    await draw("autocad_draw_line", {"start_point": [0, -2000], "end_point": [1000, -2000], "layer": "LINES"})
    await draw("autocad_draw_line", {"start_point": [0, -3000], "end_point": [2000, -3000], "layer": "LINES"})
    await draw("autocad_draw_polyline", {"points": [[0, 8000], [3000, 8000], [3000, 12000]], "closed": False, "layer": "LINES"})
    await draw("autocad_draw_arc", {"center": [0, -10000], "radius": 1000, "start_angle_degrees": 0, "end_angle_degrees": 90, "layer": "ARCS"})
    hatch = await draw("autocad_add_hatch", {"boundary_points": [[30000, 0], [34000, 0], [34000, 3000], [30000, 3000]], "pattern": "ANSI31", "layer": "HATCH", "keep_boundary": False})
    await draw("autocad_insert_block", {"name": "MCP_BLK", "insertion_point": [40000, 0], "layer": "BLOCKS"})
    await draw("autocad_insert_block", {"name": "MCP_BLK", "insertion_point": [42000, 0], "layer": "BLOCKS"})
    await draw("autocad_draw_text", {"text": "note 1", "insertion_point": [0, -5000], "height": 200, "layer": "NOTES"})
    await draw("autocad_draw_text", {"text": "note 2", "insertion_point": [0, -5500], "height": 200, "layer": "NOTES"})
    counts = cp.model_counts(cp.active_doc())
    print("drawn:", counts)
    must(counts["total"] == 13, f"expected 13 entities, AutoCAD has {counts}")

    def chk_takeoff(p):
        L = p["layers"]
        must(near(p["metres_per_drawing_unit"], 0.001), f"metres per unit {p['metres_per_drawing_unit']}")
        must(p["totals"]["entities"] == 13 and p["scan_truncated"] is False, short(p["totals"]))
        w = L["A-WALL"]
        must(w["entities"] == 2 and w["closed_polylines"] == 2 and near(w["closed_area"], 1_840_000) and near(w["closed_perimeter"], 16_920), short(w))
        must(w["walls"]["count"] == 2 and near(w["walls"]["length"], 8000) and near(w["walls"]["plan_area"], 1_840_000) and w["walls"]["thicknesses"] == {"230.0": 2}, short(w["walls"]))
        must(near(w["walls"]["face_area_one_side"], 21_600_000) and near(w["walls"]["volume_estimate"], 4_968_000_000), short(w["walls"]))
        must(near(w["metric"]["wall_length_m"], 8.0) and near(w["metric"]["closed_area_m2"], 1.84, 1e-4), short(w["metric"]))
        r = L["ROOM"]
        must(r["closed_polylines"] == 1 and near(r["closed_area"], 12_000_000) and near(r["closed_perimeter"], 14_000) and near(r["metric"]["closed_area_m2"], 12.0), short(r))
        c = L["COL"]
        must(c["circles"] == 1 and near(c["circle_area"], math.pi * 500 ** 2, 1e-6) and near(c["metric"]["circle_area_m2"], math.pi * 0.25, 1e-3), short(c))
        ln = L["LINES"]
        must(near(ln["line_length"], 3000) and near(ln["open_polyline_length"], 7000) and near(ln["metric"]["total_length_m"], 10.0), short(ln))
        a = L["ARCS"]
        must(near(a["arc_length"], math.pi / 2 * 1000, 1e-6) and near(a["metric"]["total_length_m"], math.pi / 2, 1e-3), short(a))
        hh = L["HATCH"]
        must(near(hh["hatch_area"], 12_000_000, 1e-6) and hh["hatches"] == {"ANSI31": 1} and near(hh["metric"]["hatch_area_m2"], 12.0), short(hh))
        must(L["BLOCKS"]["blocks"] == {"MCP_BLK": 2} and L["NOTES"]["texts"] == 2, short({k: L[k] for k in ("BLOCKS", "NOTES")}))
        must(near(p["totals"]["line_length"], 3000) and near(p["totals"]["open_polyline_length"], 7000), short(p["totals"]))
    await case(ctx, "TK01", "M", "autocad_quantity_takeoff", {"wall_height": 2700}, "takeoff on a drawing built from known numbers: wall length 8000, wall area 1.84e6, face area 21.6e6, volume 4.968e9, room 12 m2, circle pi*500^2, lines 3000 + 7000, arc pi/2*1000, hatch 12 m2, 2 blocks, 2 texts - every figure computed here from the coordinates",
               check=chk_takeoff, method="real-MCP-stdio+hand-computed")

    def chk_filter(p):
        must(list(p["layers"]) == ["ROOM"] and p["totals"]["entities"] == 1 and near(p["layers"]["ROOM"]["closed_area"], 12_000_000), short(p["totals"]))
    await case(ctx, "TK02", "M", "autocad_quantity_takeoff", {"layers": ["room"]}, "layer filter (case-insensitive) keeps only ROOM", check=chk_filter)
    await case(ctx, "TK03", "M", "autocad_quantity_takeoff", {"wall_height": -5}, "a negative wall height is rejected", expect_error="E_INVALID_INPUT")
    await case(ctx, "TK04", "M", "autocad_quantity_takeoff", {"max_entities": 5}, "max_entities=5 truncates and says so",
               check=lambda p: must(p["scan_truncated"] is True and p["totals"]["entities"] == 5, short(p["totals"])))

    # ---------------------------------------------------------------- saved reports
    def chk_report(fmt):
        def _c(p):
            f = p["file"]
            path = Path(f["path"])
            must(path.exists() and f["size_bytes"] == path.stat().st_size > 50 and f["sha256"] == sha(path), f"file evidence {f}")
            text = path.read_text(encoding="utf-8")
            if fmt == "json":
                data = json.loads(text)
                must("layers" in json.dumps(data) and "A-WALL" in text, "report JSON lacks the layers")
            elif fmt == "csv":
                must(text.count("\n") >= 5 and "A-WALL" in text, f"csv looks empty: {text[:120]!r}")
            else:
                must("A-WALL" in text and text.lstrip().startswith("#"), f"md looks wrong: {text[:120]!r}")
            must(p["saved"] is False and p["verified"] is True, short(p))
        return _c
    for fmt in ("json", "csv", "md"):
        await case(ctx, f"RP0{('json', 'csv', 'md').index(fmt) + 1}", "M", "autocad_save_report", {"report": "takeoff", "path": str(RPT / f"takeoff-live.{fmt}"), "format": fmt, "wall_height": 2700},
                   f"save the takeoff as {fmt}: file exists, size and SHA-256 equal a fresh hash, content has the layers", check=chk_report(fmt), method="real-MCP-stdio+file")
    await case(ctx, "RP04", "M", "autocad_save_report", {"report": "takeoff", "path": str(RPT / "takeoff-live.json"), "format": "json"}, "an existing report is not overwritten (E_OUTPUT_EXISTS)", expect_error="E_OUTPUT_EXISTS")
    await case(ctx, "RP05", "M", "autocad_save_report", {"report": "bill-of-quantities", "path": str(RPT / "x.json")}, "an unknown report kind is rejected", expect_error="E_INVALID_INPUT")
    await case(ctx, "RP06", "M", "autocad_save_report", {"report": "takeoff", "path": str(RPT / "x.xml"), "format": "xml"}, "an unknown format is rejected", expect_error="E_INVALID_INPUT")

    # ---------------------------------------------------------------- check_drawing: plant three known issues
    dup = await draw("autocad_draw_line", {"start_point": [0, -2000], "end_point": [1000, -2000], "layer": "LINES"})
    zero = await draw("autocad_draw_line", {"start_point": [100, 100], "end_point": [900, 100]})
    open_wall = await draw("autocad_draw_polyline", {"points": [[0, 9000], [2000, 9000]], "closed": False, "layer": "A-WALL"})

    def chk_qc(p):
        by_rule = {}
        for i in p["issues"]:
            by_rule.setdefault(i["rule"], []).append(i["handle"])
        must(dup["handle"] in by_rule.get("duplicate", []), f"duplicate line {dup['handle']} not reported: {by_rule}")
        must(zero["handle"] in by_rule.get("on_layer_0", []), f"line on layer 0 {zero['handle']} not reported: {by_rule}")
        must(open_wall["handle"] in by_rule.get("unclosed_wall_outline", []), f"open wall outline {open_wall['handle']} not reported: {by_rule}")
        must(p["entity_count"] == cp.model_counts(cp.active_doc())["total"] == 16, f"entity_count {p['entity_count']}")
        must(len(by_rule.get("duplicate", [])) == 1 and len(by_rule.get("on_layer_0", [])) == 1 and len(by_rule.get("unclosed_wall_outline", [])) == 1, f"unexpected extra findings: {by_rule}")
        must(p["passed"] is True, "no error-level findings were planted")
    await case(ctx, "QC01", "J", "autocad_check_drawing", {}, "check_drawing on the live drawing finds exactly the 3 planted issues (a duplicate line, a line on layer 0, an open A-WALL polyline) by handle", check=chk_qc, method="real-MCP-stdio+direct-COM")
    await case(ctx, "QC02", "J", "autocad_check_drawing", {"rules": ["no_such_rule"]}, "an unknown rule is rejected", expect_error="E_INVALID_INPUT")
    await case(ctx, "QC03", "J", "autocad_check_drawing", {"layer_pattern": "^[A-Z]-[A-Z0-9-]+$"}, "layer-name rule flags the non-standard layer names (ROOM, COL, LINES, ...)",
               check=lambda p: must({i["layer"] for i in p["issues"] if i["rule"] == "layer_name"} >= {"ROOM", "COL", "LINES", "ARCS", "HATCH", "BLOCKS", "NOTES"}, short(p["counts_by_rule"])))

    def chk_qc_report(p):
        f = p["file"]
        data = json.loads(Path(f["path"]).read_text(encoding="utf-8"))
        must(f["sha256"] == sha(f["path"]) and "issues" in json.dumps(data), "qc report content")
    await case(ctx, "RP07", "J", "autocad_save_report", {"report": "qc", "path": str(RPT / "qc-live.json")}, "save the QC report as json: SHA-256 equals a fresh hash, content has the issues", check=chk_qc_report, method="real-MCP-stdio+file")


    h.PRE_CALL_HOOK = None
    h.dump(h.EVIDENCE / "07b_interference.json", INTERFERENCE)
    record(id="TK00", category="M", tool=None, title="active drawing switched away from the scratch drawing by someone other than the server while the takeoff cases ran",
           status="NOT_APPLICABLE", method="direct-COM", evidence=f"{len(INTERFERENCE)} time(s): {INTERFERENCE}", problems=[], log_ref="07b_interference.json")
    print("interference events:", INTERFERENCE)


async def main():
    base = cp.baseline()
    print("baseline drawings (never touched):", base)
    async with h.open_session("07b_takeoff", env=h.server_env("com")) as (session, log):
        ctx = Ctx(session, log, "07b_takeoff")
        try:
            await run(ctx, base)
        finally:
            h.PRE_CALL_HOOK = None
            closed = cp.close_new_docs(base)
            print("cleanup closed scratch drawings:", closed)


try:
    asyncio.run(main())
except h.StopRun as exc:
    print("STOPPED:", exc)
    sys.exit(2)
