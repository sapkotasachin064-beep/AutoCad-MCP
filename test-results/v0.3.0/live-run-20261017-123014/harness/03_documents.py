"""Step 3 - two scratch drawings: create / list / pin / activate / save / close / open, the user-switches-tab
pinning case, and autocad_create_test_drawing_with_line. Real MCP stdio, COM backend, independent direct-COM
and file read-backs. Only drawings created here (or files under this run's workspace) are ever opened.
"""

import asyncio
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_harness as h  # noqa: E402
import com_probe as cp  # noqa: E402
from cases import Ctx, acase, case, close, mark, must, observe, pt_close, record, short, tool  # noqa: E402

WS = h.WORKSPACE
SCR = WS / "scratch"
TD = WS / "test-drawings"
SCR.mkdir(parents=True, exist_ok=True)
S1_PATH, S2_PATH = SCR / "live_s1.dwg", SCR / "live_s2.dwg"
DWG_CODE = {"R2000": b"AC1015", "R2004": b"AC1018", "R2007": b"AC1021", "R2010": b"AC1024", "R2013": b"AC1027", "R2018": b"AC1032"}


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unsaved_id(name: str) -> str:
    return f"unsaved:{name.lower()}"


def path_id(path) -> str:
    return f"path:{str(path).lower()}"


async def run(ctx: Ctx, base):
    d = ctx.data

    # ------------------------------------------------------------------ baseline
    def chk_list0(p):
        mine = cp.doc_list()
        must(p["count"] == len(mine) == len(base), f"tool says {p['count']}, direct COM {len(mine)}, baseline {len(base)}")
    await case(ctx, "DOC01", "B", "autocad_list_drawings", {}, "no drawing open at the start: tool and direct COM agree", check=chk_list0, method="real-MCP-stdio+direct-COM")

    # ------------------------------------------------------------------ create two scratch drawings
    def chk_new1(p):
        must(p["status"] == "ok" and p["verified"] is True and p["saved"] is False, short(p))
        must(p["drawing_identity"] == unsaved_id(p["drawing_name"]), f"identity {p['drawing_identity']}")
        d["s1"] = {"name": p["drawing_name"], "identity": p["drawing_identity"]}
        docs = cp.doc_list()
        must(len(docs) == len(base) + 1, f"direct COM drawing count {len(docs)}")
        act = [x for x in docs if x["active"]]
        must(len(act) == 1 and act[0]["name"] == p["drawing_name"] and act[0]["full_name"] == "", f"active {act}")
    await case(ctx, "DOC02", "B", "autocad_create_new_drawing", {}, "create scratch drawing 1: becomes the active, unsaved drawing (direct COM agrees)", check=chk_new1, method="real-MCP-stdio+direct-COM")

    def chk_pin1(p):
        must(p["pinned_document"] == d["s1"]["identity"], short(p))
    await case(ctx, "DOC03", "T", "autocad_pin_document", {}, "pin the session to drawing 1", check=chk_pin1)

    def chk_refuse_new(p):
        must(cp.doc_count() == len(base) + 1, "a refused create must not add a drawing")
    await case(ctx, "DOC04", "T", "autocad_create_new_drawing", {}, "creating a drawing while pinned is refused (E_DOCUMENT_PINNED) and adds nothing", expect_error="E_DOCUMENT_PINNED", check=chk_refuse_new, method="real-MCP-stdio+direct-COM")

    def chk_new2(p):
        d["s2"] = {"name": p["drawing_name"], "identity": p["drawing_identity"]}
        must(p["pinned"] is True and p["previous_pin"] == d["s1"]["identity"], short(p))
        must(cp.doc_count() == len(base) + 2 and cp.active_name() == p["drawing_name"], f"docs {cp.doc_list()}")
    await case(ctx, "DOC05", "B", "autocad_create_new_drawing", {"pin": True}, "pin=true creates scratch drawing 2 and moves the pin to it", check=chk_new2, method="real-MCP-stdio+direct-COM")

    def chk_list2(p):
        must(p["count"] == 2 and p["pinned_document"] == d["s2"]["identity"], short(p))
        act = [r for r in p["drawings"] if r["active"]]
        must(len(act) == 1 and act[0]["name"] == d["s2"]["name"], f"active {act}")
        mine = {x["name"]: x for x in cp.doc_list()}
        for r in p["drawings"]:
            must(r["name"] in mine and mine[r["name"]]["full_name"] == (r["path"] or ""), f"{r} vs {mine}")
    await case(ctx, "DOC06", "B", "autocad_list_drawings", {}, "list shows both drawings, drawing 2 active and pinned (direct COM agrees)", check=chk_list2, method="real-MCP-stdio+direct-COM")

    # a first change in drawing 2
    out = await tool(ctx, "autocad_draw_line", {"start_point": [0, 0], "end_point": [100, 100]}, label="setup-s2-line")
    must(not out["is_error"], short(out["payload"]))
    d["s2_line"] = out["payload"]["handle"]

    # ------------------------------------------------------------------ activate / pin
    def chk_switch_refused(p):
        must(cp.active_name() == d["s2"]["name"], "active drawing must not change on a refused switch")
    await case(ctx, "DOC07", "T", "autocad_activate_drawing", {"identity": d["s1"]["identity"]}, "activating another drawing while pinned is refused and nothing switches",
               expect_error="E_DOCUMENT_PINNED", check=chk_switch_refused, method="real-MCP-stdio+direct-COM")

    def chk_activate1(p):
        must(p["verified"] is True and p["pinned"] is True and p["previous_pin"] == d["s2"]["identity"], short(p))
        must(cp.active_name() == d["s1"]["name"], f"direct COM active {cp.active_name()}")
    await case(ctx, "DOC08", "T", "autocad_activate_drawing", {"identity": d["s1"]["identity"], "pin": True}, "activate drawing 1 with pin=true: switches in AutoCAD and moves the pin", check=chk_activate1, method="real-MCP-stdio+direct-COM")

    # ------------------------------------------------------------------ the user clicks another tab while the session is pinned
    async def user_switch():
        s1_doc, s2_doc = cp.find_doc(name=d["s1"]["name"]), cp.find_doc(name=d["s2"]["name"])
        before = (cp.retry(lambda: s1_doc.ModelSpace.Count), cp.retry(lambda: s2_doc.ModelSpace.Count))
        cp.activate(s2_doc)  # simulated user action: clicks the other tab (direct COM)
        must(cp.active_name() == d["s2"]["name"], "simulated tab switch failed")
        w = await tool(ctx, "autocad_draw_line", {"start_point": [5, 5], "end_point": [50, 5]}, label="DOC09-write")
        must(w["is_error"] and h.error_code(w) == "E_DOCUMENT_CHANGED", f"write after tab switch: {short(w['payload'])}")
        r = await tool(ctx, "autocad_list_entities", {}, label="DOC09-read")
        must(r["is_error"] and h.error_code(r) == "E_DOCUMENT_CHANGED", f"read after tab switch: {short(r['payload'])}")
        after = (cp.retry(lambda: s1_doc.ModelSpace.Count), cp.retry(lambda: s2_doc.ModelSpace.Count))
        must(before == after, f"entity counts changed {before} -> {after}")
        cp.activate(s1_doc)  # the user goes back
        ok = await tool(ctx, "autocad_draw_line", {"start_point": [5, 5], "end_point": [50, 5]}, label="DOC09-after-return")
        must(not ok["is_error"], short(ok["payload"]))
        d["s1_line"] = ok["payload"]["handle"]
        counts = (cp.retry(lambda: s1_doc.ModelSpace.Count), cp.retry(lambda: s2_doc.ModelSpace.Count))
        must(counts == (1, 1), f"after returning, the line went to drawing 1: counts {counts}")
        return f"write and read refused with E_DOCUMENT_CHANGED while drawing 2 was active (counts stayed {before}); after the user returned the line went to drawing 1 only (counts {counts})"
    await acase(ctx, "DOC09", "T", "pinning", "user switches drawing tab while pinned: every tool refuses with E_DOCUMENT_CHANGED, nothing is drawn in the wrong drawing, work resumes after returning", user_switch, tool_name="autocad_pin_document")

    def chk_unpin(p):
        must(p["previous_pin"] == d["s1"]["identity"] and p["pinned_document"] is None, short(p))
    await case(ctx, "DOC10", "T", "autocad_unpin_document", {}, "unpin releases the pin", check=chk_unpin)

    def chk_notfound(p):
        pass
    out = await case(ctx, "DOC11", "T", "autocad_activate_drawing", {"identity": "unsaved:no-such-drawing.dwg"}, "unknown identity -> E_DOCUMENT_NOT_FOUND listing the open drawings", expect_error="E_DOCUMENT_NOT_FOUND",
                     check=lambda p: must(sorted(p["error"]["details"]["open"]) == sorted([d["s1"]["identity"], d["s2"]["identity"]]), short(p["error"].get("details"))))

    # ------------------------------------------------------------------ save / overwrite / normal save
    out = await tool(ctx, "autocad_activate_drawing", {"identity": d["s1"]["identity"]}, label="setup-activate-s1")
    must(not out["is_error"], short(out["payload"]))

    def chk_save1(p):
        must(p["saved"] is True and p["verified"] is True and p["unsaved_changes"] is False, short(p))
        f = p["file"]
        must(Path(f["path"]).resolve() == S1_PATH.resolve(), f"path {f['path']}")
        must(f["size_bytes"] == S1_PATH.stat().st_size > 1000, f"size {f['size_bytes']} vs disk {S1_PATH.stat().st_size}")
        must(S1_PATH.read_bytes()[:6] == DWG_CODE["R2018"], f"header {S1_PATH.read_bytes()[:6]!r}")
        if f.get("sha256"):
            must(f["sha256"] == sha(S1_PATH), "reported SHA-256 differs from a fresh hash of the file")
        must(p["drawing_identity"] == path_id(S1_PATH), f"identity {p['drawing_identity']}")
        doc = cp.find_doc(full_name=str(S1_PATH))
        must(doc is not None and cp.retry(lambda: doc.Saved), "direct COM: drawing 1 should now be named live_s1.dwg and clean")
        d["s1"]["identity"] = p["drawing_identity"]
        d["s1_sha"] = sha(S1_PATH)
    await case(ctx, "DOC12", "B", "autocad_save_drawing", {"path": str(S1_PATH)}, "save drawing 1 as live_s1.dwg (R2018): DWG header AC1032, size and SHA-256 re-read from disk, identity becomes the path",
               check=chk_save1, method="real-MCP-stdio+direct-COM+file")

    out = await tool(ctx, "autocad_activate_drawing", {"identity": d["s2"]["identity"]}, label="setup-activate-s2")
    must(not out["is_error"], short(out["payload"]))

    def chk_save2(p):
        must(p["saved"] is True and p["verified"] is True and p["version"] == "R2010", short(p))
        must(S2_PATH.read_bytes()[:6] == DWG_CODE["R2010"], f"header {S2_PATH.read_bytes()[:6]!r}")
        d["s2"]["identity"] = p["drawing_identity"]
        d["s2_sha"] = sha(S2_PATH)
    await case(ctx, "DOC13", "B", "autocad_save_drawing", {"path": str(S2_PATH), "version": "R2010"}, "save drawing 2 as live_s2.dwg with version R2010: header AC1024", check=chk_save2, method="real-MCP-stdio+file")

    def chk_overwrite_refused(p):
        must(sha(S1_PATH) == d["s1_sha"], "refused save must leave the existing file byte-identical")
        doc = cp.find_doc(full_name=str(S2_PATH))
        must(doc is not None, "drawing 2 must still be named live_s2.dwg")
    await case(ctx, "DOC14", "B", "autocad_save_drawing", {"path": str(S1_PATH)}, "save-as onto another existing file is refused (E_OUTPUT_EXISTS), file untouched, drawing keeps its name",
               expect_error="E_OUTPUT_EXISTS", check=chk_overwrite_refused, method="real-MCP-stdio+direct-COM+file")

    out = await tool(ctx, "autocad_draw_circle", {"center": [50, 50], "radius": 10}, label="setup-s2-circle")
    must(not out["is_error"], short(out["payload"]))

    def chk_plain_save(p):
        must(p["saved"] is True and p["verified"] is True, short(p))
        must(sha(S2_PATH) != d["s2_sha"], "normal Save after adding a circle must change the file")
        d["s2_sha"] = sha(S2_PATH)
        must(S2_PATH.read_bytes()[:6] == DWG_CODE["R2018"] or S2_PATH.read_bytes()[:6] == DWG_CODE["R2010"], "header changed unexpectedly")
    await case(ctx, "DOC15", "B", "autocad_save_drawing", {}, "plain Save (no path) of the changed drawing 2 rewrites its own file", check=chk_plain_save, method="real-MCP-stdio+file")

    # ------------------------------------------------------------------ close protection
    out = await tool(ctx, "autocad_activate_drawing", {"identity": d["s1"]["identity"]}, label="setup-activate-s1b")
    must(not out["is_error"], short(out["payload"]))
    out = await tool(ctx, "autocad_draw_circle", {"center": [20, 20], "radius": 5}, label="setup-s1-unsaved-circle")
    must(not out["is_error"], short(out["payload"]))

    def chk_unsaved_refused(p):
        doc = cp.find_doc(full_name=str(S1_PATH))
        must(doc is not None, "refused close must leave the drawing open")
        must(not cp.retry(lambda: doc.Saved), "drawing 1 should still have unsaved changes")
    await case(ctx, "DOC16", "B", "autocad_close_drawing", {"identity": d["s1"]["identity"]}, "closing a drawing with unsaved changes is refused (E_UNSAVED_CHANGES), drawing stays open",
               expect_error="E_UNSAVED_CHANGES", check=chk_unsaved_refused, method="real-MCP-stdio+direct-COM")

    def chk_discard(p):
        must(p["verified"] is True and p["discarded_changes"] is True, short(p))
        must(cp.find_doc(full_name=str(S1_PATH)) is None, "drawing 1 should be gone from AutoCAD")
        must(cp.doc_count() == 1, f"one drawing left, got {cp.doc_count()}")
    await case(ctx, "DOC17", "B", "autocad_close_drawing", {"identity": d["s1"]["identity"], "discard_changes": True}, "close with discard_changes=true: closed in AutoCAD (direct COM), changes thrown away",
               check=chk_discard, method="real-MCP-stdio+direct-COM")

    # ------------------------------------------------------------------ open (read-only default), already open, read-only save
    def chk_open_ro(p):
        must(p["verified"] is True and p["already_open"] is False and p["read_only"] is True, short(p))
        must(p["drawing_identity"] == path_id(S1_PATH), p["drawing_identity"])
        doc = cp.find_doc(full_name=str(S1_PATH))
        must(doc is not None and cp.retry(lambda: doc.ReadOnly), "direct COM: opened drawing should be read-only")
        ents = cp.model_entities(doc)
        must(len(ents) == 1 and ents[0]["object_name"] == "AcDbLine" and ents[0]["end"][:2] == (50.0, 5.0),
             f"saved content should be the single line (5,5)-(50,5), got {ents}")
        must(not any(e["object_name"] == "AcDbCircle" for e in ents), "the discarded circle must not be in the file")
        d["s1"]["identity"] = p["drawing_identity"]
    await case(ctx, "DOC18", "B", "autocad_open_drawing", {"path": str(S1_PATH)}, "re-open live_s1.dwg (read-only by default): read-only in AutoCAD, content is exactly what was saved (the discarded circle is absent)",
               check=chk_open_ro, method="real-MCP-stdio+direct-COM")

    await case(ctx, "DOC19", "B", "autocad_save_drawing", {}, "plain Save on a read-only drawing is refused with E_INVALID_INPUT", expect_error="E_INVALID_INPUT")

    def chk_open_again(p):
        must(p["already_open"] is True and p["verified"] is True, short(p))
        must(cp.doc_count() == 2, f"no extra window expected, got {cp.doc_list()}")
    await case(ctx, "DOC20", "B", "autocad_open_drawing", {"path": str(S1_PATH)}, "opening an already-open file only activates it (no second window)", check=chk_open_again, method="real-MCP-stdio+direct-COM")

    # ------------------------------------------------------------------ read-write open, edit, plain save, close by identity
    out = await tool(ctx, "autocad_close_drawing", {"identity": d["s2"]["identity"]}, label="setup-close-s2")
    must(not out["is_error"] and out["payload"]["verified"] is True, short(out["payload"]))

    def chk_open_rw(p):
        must(p["verified"] is True and p["read_only"] is False and p["already_open"] is False, short(p))
        doc = cp.find_doc(full_name=str(S2_PATH))
        must(doc is not None and not cp.retry(lambda: doc.ReadOnly), "direct COM: drawing should be editable")
        ents = cp.model_entities(doc)
        types = sorted(e["object_name"] for e in ents)
        must(types == ["AcDbCircle", "AcDbLine"], f"live_s2.dwg should hold the line and the circle, got {types}")
        d["s2"]["identity"] = p["drawing_identity"]
    await case(ctx, "DOC21", "B", "autocad_open_drawing", {"path": str(S2_PATH), "read_only": False}, "open live_s2.dwg editable (read_only=false): content is the saved line + circle", check=chk_open_rw, method="real-MCP-stdio+direct-COM")

    out = await tool(ctx, "autocad_draw_text", {"text": "reopened", "insertion_point": [0, -20], "height": 5}, label="setup-s2-text")
    must(not out["is_error"], short(out["payload"]))
    before = sha(S2_PATH)

    def chk_save_rw(p):
        must(p["saved"] is True and p["verified"] is True, short(p))
        must(sha(S2_PATH) != before, "plain Save of an editable re-opened drawing must change the file")
    await case(ctx, "DOC22", "B", "autocad_save_drawing", {}, "plain Save on the re-opened editable drawing works and changes the file", check=chk_save_rw, method="real-MCP-stdio+file")

    # ------------------------------------------------------------------ open negatives (nothing may open)
    n_before = cp.doc_count()
    await case(ctx, "DOC23", "B", "autocad_open_drawing", {"path": str(SCR / "does-not-exist.dwg")}, "opening a missing file gives a typed error and opens nothing", expect_error="ANY",
               check=lambda p: must(cp.doc_count() == n_before, "drawing count changed"), method="real-MCP-stdio+direct-COM")
    await case(ctx, "DOC24", "B", "autocad_open_drawing", {"path": str(h.OUTSIDE / "x.dwg")}, "opening a path outside the allowed folder is refused before AutoCAD is asked", expect_error="E_OUTPUT_PATH_REJECTED",
               check=lambda p: must(cp.doc_count() == n_before, "drawing count changed"), method="real-MCP-stdio+direct-COM")
    await case(ctx, "DOC25", "B", "autocad_open_drawing", {"path": str(SCR / "notes.txt")}, "a .txt path is refused (E_INVALID_INPUT)", expect_error=("E_INVALID_INPUT", "E_FILE_NOT_FOUND"))

    # ------------------------------------------------------------------ DXF: export a copy, open it
    dxf = SCR / "live_export.dxf"

    def chk_export(p):
        must(p["verified"] is True and p["document_unchanged"] is True, short(p))
        must(dxf.read_bytes()[:200].count(b"SECTION") >= 1, "no DXF SECTION in header")
    await case(ctx, "DOC26", "N", "autocad_export_dxf", {"path": str(dxf)}, "export a DXF copy of the active drawing; the open drawing keeps its name", check=chk_export, method="real-MCP-stdio+file")

    def chk_open_dxf(p):
        must(p["verified"] is True and p["drawing_identity"] == path_id(dxf), short(p))
        doc = cp.find_doc(full_name=str(dxf))
        must(doc is not None, "DXF not open in AutoCAD")
        types = sorted(e["object_name"] for e in cp.model_entities(doc))
        must(types == ["AcDbCircle", "AcDbLine", "AcDbText"], f"DXF content {types}")
    await case(ctx, "DOC27", "B", "autocad_open_drawing", {"path": str(dxf)}, "open the exported DXF (read-only): AutoCAD shows the same line, circle and text", check=chk_open_dxf, method="real-MCP-stdio+direct-COM")

    # ------------------------------------------------------------------ autocad_create_test_drawing_with_line
    TD.mkdir(parents=True, exist_ok=True)
    n0 = cp.doc_count()

    def chk_test_drawing(p):
        must(p["status"] == "ok" and p["verified"] is True and p["saved"] is True, short(p))
        fp = Path(p["file_path"])
        must(fp.exists() and fp.parent.resolve() == TD.resolve() and fp.name.startswith("mcp_test_") and fp.suffix == ".dwg", f"file {fp}")
        must(fp.stat().st_size > 1000 and fp.read_bytes()[:4] == b"AC10", f"size {fp.stat().st_size} header {fp.read_bytes()[:6]!r}")
        doc = cp.find_doc(full_name=str(fp))
        must(doc is not None, "direct COM: the saved drawing should be open under that file name")
        ents = cp.model_entities(doc)
        must(len(ents) == 1 and ents[0]["object_name"] == "AcDbLine", f"model space {ents}")
        must(ents[0]["handle"] == p["line_handle"], f"handle {ents[0]['handle']} vs {p['line_handle']}")
        must(ents[0]["start"] == (0.0, 0.0, 0.0) and ents[0]["end"] == (100.0, 100.0, 0.0), f"line {ents[0]['start']} -> {ents[0]['end']}")
        must(cp.doc_count() == n0 + 1, "exactly one new drawing expected")
        d["test_dwg"] = str(fp)
    await case(ctx, "TD01", "B", "autocad_create_test_drawing_with_line", {"output_dir": str(TD)},
               "create_test_drawing_with_line: DWG saved under output_dir, one line (0,0,0)-(100,100,0) with the reported handle (direct COM), file is a DWG", check=chk_test_drawing,
               method="real-MCP-stdio+direct-COM+file")

    def chk_default_dir(p):
        fp = Path(p["file_path"])
        must(fp.exists() and fp.parent.resolve() == WS.resolve(), f"default folder should be AUTOCAD_MCP_OUTPUT_DIR ({WS}), got {fp.parent}")
    await case(ctx, "TD02", "B", "autocad_create_test_drawing_with_line", {}, "without output_dir the file goes to AUTOCAD_MCP_OUTPUT_DIR", check=chk_default_dir, method="real-MCP-stdio+file")

    outside_dir = h.OUTSIDE / "test-drawings"
    n1 = cp.doc_count()
    out = await tool(ctx, "autocad_create_test_drawing_with_line", {"output_dir": str(outside_dir)}, label="TD03")
    wrote = sorted(str(x) for x in outside_dir.glob("*.dwg")) if outside_dir.exists() else []
    rejected = out["is_error"] and h.error_code(out) == "E_OUTPUT_PATH_REJECTED"
    problems = []
    if not rejected:
        problems.append(f"output_dir outside AUTOCAD_MCP_ALLOWED_DIRS ({WS}) was not rejected: result {short(out['payload'], 220)}; files created there: {wrote}")
    record(id="TD03", category="R", tool="autocad_create_test_drawing_with_line", title="output_dir outside AUTOCAD_MCP_ALLOWED_DIRS must be rejected (AGENTS.md invariant 8: never write outside the allowed folders)",
           status="PASS" if rejected and not wrote else "FAIL", method="real-MCP-stdio+file", evidence=short(out["payload"], 300) + f" | files in outside folder: {wrote}",
           problems=problems, args={"output_dir": str(outside_dir)}, log_ref=f"{ctx.session_name}.jsonl#{ctx.log.n}", ms=out["ms"])
    print(f"[{'PASS' if rejected and not wrote else 'FAIL'}] TD03 autocad_create_test_drawing_with_line: output_dir outside the allowed folder" + ("" if rejected else f"\n       -> {problems[0][:500]}"))
    if not rejected:
        observe("OBS-testdrawing-path-policy", "autocad_create_test_drawing_with_line", "medium",
                "autocad_create_test_drawing_with_line writes to any output_dir; core.paths.output_path (allowed-folder policy) is not applied.", short(out["payload"], 300))
    if cp.doc_count() > n1:
        pass  # the scratch drawing it created is closed by the cleanup below

    # ------------------------------------------------------------------ final listing agrees with AutoCAD
    def chk_final(p):
        mine = cp.doc_list()
        must(p["count"] == len(mine), f"{p['count']} vs {len(mine)}")
    await case(ctx, "DOC30", "B", "autocad_list_drawings", {}, "final listing agrees with AutoCAD (direct COM)", check=chk_final, method="real-MCP-stdio+direct-COM")


async def main():
    base = cp.baseline()
    print("baseline drawings (never touched):", base)
    async with h.open_session("03_documents", env=h.server_env("com")) as (session, log):
        ctx = Ctx(session, log, "03_documents")
        try:
            await run(ctx, base)
        finally:
            closed = cp.close_new_docs(base)
            print("cleanup closed scratch drawings:", closed)
            h.dump(h.EVIDENCE / "03_documents_cleanup.json", {"closed": closed, "docs_after": cp.doc_list()})


try:
    asyncio.run(main())
except h.StopRun as exc:
    print("STOPPED:", exc)
    sys.exit(2)
