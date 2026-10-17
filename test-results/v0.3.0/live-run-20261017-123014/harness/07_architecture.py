"""Step 7 - stair, sheet, quantity takeoff, check_drawing and save_report on a real AutoCAD.

Drawn geometry is read back entity by entity with direct COM and compared with the plan the tool itself
announced in its dry run (tag -> handle), and the takeoff numbers are compared with values computed here
from the coordinates that were drawn. Scratch drawings only.
"""

import asyncio
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


async def run(ctx: Ctx, base):
    d = ctx.data
    # ====================================================================== stairs (calculation, plan, drawing)
    def chk_design(p):
        ftf = 3000.0
        risers = math.ceil(ftf / 190.0)
        riser = ftf / risers
        must(p["risers"] == risers == 16 and near(p["riser_height"], riser) and p["treads"] == 15, short(p))
        must(near(p["tread_depth"], 250) and near(p["run_length"], 3750) and near(p["step_relation_2R_plus_G"], 2 * riser + 250), short(p))
        must(near(p["pitch_degrees"], math.degrees(math.atan2(riser, 250))) and p["all_checks_pass"] is True, short(p))
        must(p["limits_source"] == "rule_of_thumb_defaults_not_a_building_code", "honesty label missing")
    await case(ctx, "ST01", "L", "autocad_design_stair", {"floor_to_floor": 3000}, "stair for 3000 mm on the live backend: 16 risers of 187.5, 15 treads of 250, 3750 run, 2R+G and pitch re-derived here; labelled as rule-of-thumb, not a code", check=chk_design)
    await case(ctx, "ST02", "L", "autocad_design_stair", {"floor_to_floor": 0}, "zero rise rejected", expect_error="E_INVALID_INPUT")

    await new_doc(ctx)
    doc = cp.active_doc()
    n0 = cp.retry(lambda: doc.ModelSpace.Count)

    holder = {}

    def chk_dry(p):
        must(p["dry_run"] is True and p["entity_count"] == 18 and p["counts_by_layer"] == {"A-FLOR-STRS": 17, "A-ANNO-NOTE": 1}, short(p["counts_by_layer"]))
        must(p["state"]["executed"] is False, short(p["state"]))
        must(cp.retry(lambda: cp.active_doc().ModelSpace.Count) == n0, "a dry run must not draw anything (direct COM)")
        holder["plan"] = p["plan"]
    await case(ctx, "ST03", "L", "autocad_draw_stair_plan", {"floor_to_floor": 3000, "origin": [30000, 0], "dry_run": True}, "stair plan dry run: 18 entities announced, nothing drawn (direct COM count unchanged)", check=chk_dry, method="real-MCP-stdio+direct-COM")

    def chk_draw(p):
        must(p["verified"] is True and p["entity_count"] == 18 and len(p["handles"]) == 18, short({k: p.get(k) for k in ("verified", "entity_count")}))
        counts = cp.model_counts(cp.active_doc())
        must(counts["total"] == n0 + 18 and counts["by_layer"] == {"A-FLOR-STRS": 17, "A-ANNO-NOTE": 1}, f"direct COM counts {counts}")
        checked, problems = verify_against_plan(holder["plan"], p["handles"])
        must(checked == 18 and not problems, f"{checked} checked; {problems[:3]}")
        lp = cp.layer_props(cp.active_doc(), "A-FLOR-STRS"), cp.layer_props(cp.active_doc(), "A-ANNO-NOTE")
        must(lp[0] and lp[0]["color"] == 2 and lp[1] and lp[1]["color"] == 7, f"layers {lp}")
        d["stair_handles"] = p["handles"]
    await case(ctx, "ST04", "L", "autocad_draw_stair_plan", {"floor_to_floor": 3000, "origin": [30000, 0]}, "draw the stair plan: all 18 entities read back from AutoCAD one by one equal the announced plan (geometry, layer, text, height); layers and colours exist",
               check=chk_draw, method="real-MCP-stdio+direct-COM")

    async def stair_geometry():
        nosings = []
        for tag, hd in d["stair_handles"].items():
            if tag.startswith("stair:nosing:"):
                e = cp.describe(cp.entity(cp.active_doc(), hd))
                nosings.append(e)
        ys = sorted(round(e["start"][1], 6) for e in nosings)
        must(ys == [250.0 * k for k in range(1, 15)], f"nosing y-positions {ys}")
        must(all(near(e["start"][0], 30000) and near(e["end"][0], 30900) for e in nosings), "nosings must span x = 30000..30900")
        outline = cp.describe(cp.entity(cp.active_doc(), d["stair_handles"]["stair:outline"]))
        must(outline["object_name"] == "AcDbPolyline" and outline["closed"] is True and pts_close(outline["coords"], [30000, 0, 30900, 0, 30900, 3750, 30000, 3750]), f"outline {outline}")
        note = cp.describe(cp.entity(cp.active_doc(), d["stair_handles"]["stair:note"]))
        must("UP 16R" in note["text"], f"note {note['text']!r}")
        return "14 nosings every 250 mm from y=250 to 3500, 900 mm wide at x=30000; closed outline 900 x 3750; note 'UP 16R' (all read from AutoCAD)"
    await acase(ctx, "ST05", "L", "autocad_draw_stair_plan", "stair geometry checked against numbers derived by hand (tread spacing, width, run, note)", stair_geometry, tool_name="autocad_draw_stair_plan")

    async def stair_east():
        r = await tool(ctx, "autocad_draw_stair_plan", {"floor_to_floor": 3000, "origin": [0, -20000], "direction_degrees": 0}, label="ST06")
        must(not r["is_error"] and r["payload"]["verified"], short(r["payload"]))
        lo, hi = bbox_com(r["payload"]["handles"]["stair:outline"])
        w, hgt = hi[0] - lo[0], hi[1] - lo[1]
        must(near(w, 3750, 1e-6, 0.01) and near(hgt, 900, 1e-6, 0.01), f"footprint {w} x {hgt}")
        must(near(lo[0], 0, 1e-6, 0.01), f"starts at x={lo[0]}")
        return f"east-climbing flight footprint {w:.1f} x {hgt:.1f} mm read from AutoCAD's bounding box"
    await acase(ctx, "ST06", "L", "autocad_draw_stair_plan", "direction 0 climbs along +X: footprint 3750 x 900 mm (AutoCAD bounding box)", stair_east, tool_name="autocad_draw_stair_plan")

    count_before = cp.retry(lambda: cp.active_doc().ModelSpace.Count)
    await case(ctx, "ST07", "L", "autocad_draw_stair_plan", {"floor_to_floor": 3000, "direction_degrees": 45}, "a 45-degree direction is refused and nothing is drawn", expect_error="E_INVALID_INPUT",
               check=lambda p: must(cp.retry(lambda: cp.active_doc().ModelSpace.Count) == count_before, "entities were added by a refused call"), method="real-MCP-stdio+direct-COM")

    # ====================================================================== sheet / title block
    fields = {"project": "MCP Live House", "title": "Stair and sheet", "drawn_by": "live campaign"}
    sheet_args = {"paper": "A3", "scale": 100, "origin": [-3000, -8000], "fields": fields}
    n1 = cp.retry(lambda: cp.active_doc().ModelSpace.Count)

    def chk_sheet_dry(p):
        must(p["entity_count"] == 20 and p["paper"] == "A3" and p["paper_mm"] == [420.0, 297.0] and p["scale"] == 100, short({k: p[k] for k in ("entity_count", "paper_mm", "scale")}))
        must(p["drawing_area"]["min"] == [-1000, -7000] and p["drawing_area"]["max"] == [38000, 20700], short(p["drawing_area"]))
        must(p["fields"]["scale"] == "1:100", short(p["fields"]))
        must(cp.retry(lambda: cp.active_doc().ModelSpace.Count) == n1, "dry run drew something")
        holder["sheet_plan"] = p["plan"]
    await case(ctx, "SH01", "L", "autocad_draw_sheet", {**sheet_args, "dry_run": True}, "A3 sheet at 1:100, dry run: 20 entities, 420 x 297 mm, usable area (-1000,-7000)..(38000,20700) as derived by hand; nothing drawn", check=chk_sheet_dry, method="real-MCP-stdio+direct-COM")

    def chk_sheet(p):
        must(p["verified"] is True and p["entity_count"] == 20 and len(p["handles"]) == 20, short({k: p.get(k) for k in ("verified", "entity_count")}))
        checked, problems = verify_against_plan(holder["sheet_plan"], p["handles"])
        must(checked == 20 and not problems, f"{checked} checked; {problems[:3]}")
        edge = cp.describe(cp.entity(cp.active_doc(), p["handles"]["sheet:edge"]))
        must(pts_close(edge["coords"], [-3000, -8000, 39000, -8000, 39000, 21700, -3000, 21700]), f"sheet edge {edge['coords']}")
        label = cp.describe(cp.entity(cp.active_doc(), p["handles"]["title:label:project"]))
        value = cp.describe(cp.entity(cp.active_doc(), p["handles"]["title:value:project"]))
        must(near(label["height"], 250) and near(value["height"], 350), f"text heights {label['height']} / {value['height']} (2.5 mm and 3.5 mm at 1:100)")
        must(value["text"] == "MCP Live House", value["text"])
        lp = cp.layer_props(cp.active_doc(), "G-ANNO-TTLB")
        must(lp and lp["color"] == 7, f"layer {lp}")
    await case(ctx, "SH02", "L", "autocad_draw_sheet", sheet_args, "draw the A3 sheet: all 20 entities read back from AutoCAD equal the plan; edge is 42000 x 29700 from the chosen origin; label / value text heights are 250 / 350 (paper 2.5 / 3.5 mm x 100)", check=chk_sheet, method="real-MCP-stdio+direct-COM")

    n2 = cp.retry(lambda: cp.active_doc().ModelSpace.Count)
    for cid, args, title in (("SH03", {"paper": "B7"}, "unknown paper size rejected"), ("SH04", {"scale": 0}, "zero scale rejected"),
                             ("SH05", {"fields": {"colour": "red"}}, "an unknown title-block field is rejected"), ("SH06", {"orientation": "diagonal"}, "unknown orientation rejected")):
        await case(ctx, cid, "L", "autocad_draw_sheet", args, title + " and nothing is drawn", expect_error="E_INVALID_INPUT",
                   check=lambda p: must(cp.retry(lambda: cp.active_doc().ModelSpace.Count) == n2, "entities were added by a refused call"), method="real-MCP-stdio+direct-COM")

    # ====================================================================== quantity takeoff on a hand-computed drawing
    await new_doc(ctx)
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


async def main():
    base = cp.baseline()
    print("baseline drawings (never touched):", base)
    async with h.open_session("07_architecture", env=h.server_env("com")) as (session, log):
        ctx = Ctx(session, log, "07_architecture")
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
