"""Step 6 - autocad_plot_pdf (and list_layouts / export_dxf) on a real AutoCAD, 'DWG To PDF.pc3'.

Every PDF is checked on disk by header, size, %%EOF, page count and page size, and its drawing content is
read with pdfplumber (independent of AutoCAD). Layout settings, BACKGROUNDPLOT and the active layout are read
straight from AutoCAD before and after every plot to prove they are restored.
"""

import asyncio
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_harness as h  # noqa: E402
import com_probe as cp  # noqa: E402
from cases import Ctx, acase, case, must, observe, record, short, tool  # noqa: E402

WS = h.WORKSPACE
PL = WS / "plots"
EX = WS / "exports"
PL.mkdir(parents=True, exist_ok=True)
EX.mkdir(parents=True, exist_ok=True)
PNG = h.EVIDENCE / "pdf_pages"
PNG.mkdir(parents=True, exist_ok=True)
TIMEOUT = 420.0


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pdf_info(path, render_as=None) -> dict:
    data = Path(path).read_bytes()
    out = {"size": len(data), "header_ok": data[:5] == b"%PDF-", "eof_ok": b"%%EOF" in data[-2048:]}
    import pdfplumber

    with pdfplumber.open(str(path)) as pdf:
        out["pages"] = len(pdf.pages)
        pg = pdf.pages[0]
        out["mm"] = [round(pg.width * 25.4 / 72, 1), round(pg.height * 25.4 / 72, 1)]
        objs = list(pg.lines) + list(pg.curves) + list(pg.rects)
        out["objects"] = len(objs)
        colors = set()
        for o in objs:
            c = o.get("stroking_color")
            if c is None:
                continue
            colors.add(tuple(round(float(x), 2) for x in c) if isinstance(c, (tuple, list)) else (round(float(c), 2),))
        out["stroke_colors"] = sorted(colors)
        out["has_red_stroke"] = (1.0, 0.0, 0.0) in colors
        if render_as:
            try:
                pg.to_image(resolution=60).save(str(PNG / render_as))
                out["png"] = render_as
            except Exception as exc:  # rendering is a convenience only
                out["png_error"] = repr(exc)[:120]
    return out


def state_equal(before: dict, after: dict) -> tuple[list[str], list[str]]:
    """(real differences, tolerated differences). The one tolerated difference is the documented one: a layout whose
    CanonicalMediaName was '' (never set) is left at the plot device's default media, because AutoCAD refuses to
    write '' back (docs/testing.md, run 1 findings)."""
    diffs, tolerated = [], []
    for key in ("BACKGROUNDPLOT", "QuietErrorMode", "ActiveLayout"):
        if before[key] != after[key]:
            diffs.append(f"{key}: {before[key]} -> {after[key]}")
    for name, settings in before["layouts"].items():
        for k, v in settings.items():
            av = after["layouts"][name][k]
            if av != v:
                msg = f"layout {name} {k}: {v!r} -> {av!r}"
                (tolerated if (k == "CanonicalMediaName" and v == "") else diffs).append(msg)
    return diffs, tolerated


def hidden_leftovers(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.name.startswith(".") and p.suffix in (".pdf", ".dxf", ".DXF"))


async def run(ctx: Ctx, base):
    d = ctx.data
    o = await tool(ctx, "autocad_create_new_drawing", {"pin": True}, label="setup")
    must(not o["is_error"], short(o["payload"]))
    u = await tool(ctx, "autocad_set_drawing_units", {"preset": "metric_mm"}, label="setup-units")
    must(not u["is_error"], short(u["payload"]))
    must((await tool(ctx, "autocad_create_layer", {"name": "MCP_RED", "color_index": 1}, label="setup-layer"))["payload"]["verified"], "layer")
    for name, args in (("autocad_draw_rectangle", {"corner1": [0, 0], "corner2": [420, 297]}),
                       ("autocad_draw_circle", {"center": [210, 148], "radius": 60, "layer": "MCP_RED"}),
                       ("autocad_draw_text", {"text": "LIVE PLOT TEST", "insertion_point": [20, 20], "height": 20}),
                       ("autocad_draw_line", {"start_point": [0, 0], "end_point": [420, 297], "layer": "MCP_RED"})):
        r = await tool(ctx, name, args, label="setup-" + name)
        must(not r["is_error"], f"{name}: {short(r['payload'])}")
    cp.retry(lambda: cp.app().ZoomExtents())
    doc = cp.active_doc()
    d["identity"] = cp.describe  # placeholder to keep ctx.data non-empty

    # ------------------------------------------------------------------ layouts
    def chk_layouts(p):
        names = cp.layout_names(cp.active_doc())
        must([r["name"] for r in p["layouts"]] == names or sorted(r["name"] for r in p["layouts"]) == sorted(names), f"{[r['name'] for r in p['layouts']]} vs {names}")
        must(p["current_layout"] == cp.retry(lambda: cp.active_doc().ActiveLayout.Name), "current layout differs")
        for r in p["layouts"]:
            mine = cp.layout_settings(cp.active_doc(), r["name"])
            must(r["plot_device"] == mine["ConfigName"] and r["paper"] == mine["CanonicalMediaName"] and r["plot_style"] == mine["StyleSheet"] and r["plot_type"] == mine["PlotType"],
                 f"layout {r['name']}: tool {r} vs direct COM {mine}")
        must(sum(1 for r in p["layouts"] if r["is_model"]) == 1, "exactly one model layout expected")
        d["layout_names"] = names
    await case(ctx, "PL00", "P", "autocad_list_layouts", {}, "list_layouts: Model + paper-space layouts, device / paper / style / plot type equal AutoCAD's own values (direct COM)", check=chk_layouts, method="real-MCP-stdio+direct-COM")

    before = cp.plot_state(doc)
    h.dump(h.EVIDENCE / "plot_state_before.json", before)

    # ------------------------------------------------------------------ model space plot
    target = PL / "model-default.pdf"

    def chk_plot1(p):
        f = p["file"]
        must(p["verified"] is True and p["model_space"] is True and p["layout"] == "Model" and p["device"] == "DWG To PDF.pc3", short(p))
        must(Path(f["path"]).resolve() == target.resolve() and f["size_bytes"] == target.stat().st_size and f["sha256"] == sha(target), "file evidence differs from the file on disk")
        info = pdf_info(target, "model-default.png")
        d["pdf1"] = info
        must(info["header_ok"] and info["eof_ok"] and info["size"] > 1500 and info["pages"] == 1, short(info))
        must(info["objects"] >= 3, f"drawing content missing in the PDF: {info}")
        must(info["has_red_stroke"], f"the red layer should plot red (no plot style): {info['stroke_colors']}")
        pm = sorted(p["paper_mm"])
        must(len(pm) == 2 and all(abs(a - b) <= 1.0 for a, b in zip(pm, sorted(info["mm"]))), f"tool paper_mm {p['paper_mm']} vs PDF page {info['mm']}")
        d["plot1_sha"] = sha(target)
        diffs, tolerated = state_equal(before, cp.plot_state(cp.active_doc()))
        d["tolerated"] = tolerated
        must(p["layout_settings_restored"] is True and not diffs, f"not restored: {diffs}; tool says {p['layout_settings_not_restored']}")
        must(bool(tolerated) == ("CanonicalMediaName" in p.get("layout_settings_left_at_device_default", [])), f"tool says left-at-default {p.get('layout_settings_left_at_device_default')} but direct COM shows {tolerated}")
        must(hidden_leftovers(PL) == [], f"hidden temp files left: {hidden_leftovers(PL)}")
    await case(ctx, "PL01", "P", "autocad_plot_pdf", {"path": str(target)}, "plot model space: a real 1-page PDF (header, %%EOF, size), page size = reported paper_mm, drawing content and the red layer present, layout settings / BACKGROUNDPLOT / active layout restored (direct COM)",
               check=chk_plot1, timeout=TIMEOUT, method="real-MCP-stdio+direct-COM+file")

    await case(ctx, "PL02", "P", "autocad_plot_pdf", {"path": str(target)}, "plotting onto an existing file is refused (E_OUTPUT_EXISTS), the file is untouched",
               expect_error="E_OUTPUT_EXISTS", check=lambda p: must(sha(target) == d["plot1_sha"], "existing PDF changed"), timeout=TIMEOUT, method="real-MCP-stdio+file")

    def chk_over(p):
        must(p["verified"] is True and pdf_info(target)["header_ok"], short(p))
        must(hidden_leftovers(PL) == [], f"hidden temp files left: {hidden_leftovers(PL)}")
    await case(ctx, "PL03", "P", "autocad_plot_pdf", {"path": str(target), "overwrite": True}, "overwrite=true replaces it with a valid PDF and leaves no temporary file", check=chk_over, timeout=TIMEOUT, method="real-MCP-stdio+file")

    # ------------------------------------------------------------------ paper selection
    async def paper():
        amb = await tool(ctx, "autocad_plot_pdf", {"path": str(PL / "paper-ambiguous.pdf"), "paper": "A"}, label="PL04-ambiguous", timeout=TIMEOUT)
        must(amb["is_error"] and h.error_code(amb) == "E_INVALID_INPUT", short(amb["payload"]))
        cands = amb["payload"]["error"]["details"]["candidates"]
        must(2 <= len(cands) <= 40 and not (PL / "paper-ambiguous.pdf").exists(), f"candidates {len(cands)}")
        first = await tool(ctx, "autocad_plot_pdf", {"path": str(PL / "paper-a3.pdf"), "paper": "ISO_full_bleed_A3"}, label="PL04-a3-partial", timeout=TIMEOUT)
        if first["is_error"]:
            must(h.error_code(first) == "E_INVALID_INPUT", short(first["payload"]))
            cands3 = first["payload"]["error"]["details"]["candidates"]
            pick = next((c for c in cands3 if (m := re.search(r"\(([\d.]+)_x_([\d.]+)_MM\)", c)) and sorted((float(m.group(1)), float(m.group(2)))) == [297.0, 420.0]), None)
            must(pick is not None, f"no A3 among {cands3}")
            first = await tool(ctx, "autocad_plot_pdf", {"path": str(PL / "paper-a3.pdf"), "paper": pick}, label="PL04-a3-exact", timeout=TIMEOUT)
        else:
            pick = "ISO_full_bleed_A3 (partial name was unique)"
        must(not first["is_error"] and first["payload"]["verified"], short(first["payload"]))
        info = pdf_info(PL / "paper-a3.pdf", "paper-a3.png")
        must(all(abs(a - b) <= 1.5 for a, b in zip(sorted(info["mm"]), [297.0, 420.0])), f"PDF page {info['mm']} for paper {pick}")
        diffs, _ = state_equal(before, cp.plot_state(cp.active_doc()))
        must(not diffs, f"not restored: {diffs}")
        return f"'A' is ambiguous (E_INVALID_INPUT, {len(cands)} candidates listed, no file); paper {pick!r} gives a PDF page of {info['mm']} mm; settings restored"
    await acase(ctx, "PL04", "P", "autocad_plot_pdf", "paper: an ambiguous name is refused with the candidate list; a listed A3 name produces an A3-sized PDF (page size read from the PDF)", paper, tool_name="autocad_plot_pdf", method="real-MCP-stdio+direct-COM+file")

    await case(ctx, "PL05", "P", "autocad_plot_pdf", {"path": str(PL / "no-layout.pdf"), "layout": "NoSuchLayout"}, "unknown layout -> E_LAYOUT_NOT_FOUND listing the layouts, no file",
               expect_error="E_LAYOUT_NOT_FOUND", check=lambda p: must(not (PL / "no-layout.pdf").exists() and "Model" in p["error"]["details"]["layouts"], short(p["error"].get("details"))), timeout=TIMEOUT, method="real-MCP-stdio+file")

    # ------------------------------------------------------------------ paper-space layout
    lay = next((n for n in d["layout_names"] if n.lower().startswith("layout")), None)
    must(lay is not None, f"no paper-space layout in {d['layout_names']}")

    def chk_layout_plot(p):
        must(p["verified"] is True and p["model_space"] is False and p["layout"].lower() == lay.lower(), short(p))
        info = pdf_info(PL / "layout1.pdf", "layout1.png")
        must(info["header_ok"] and info["eof_ok"] and info["size"] > 1000 and info["pages"] == 1, short(info))
        pm = sorted(p["paper_mm"])
        must(all(abs(a - b) <= 1.0 for a, b in zip(pm, sorted(info["mm"]))), f"paper_mm {p['paper_mm']} vs PDF {info['mm']}")
        diffs, _ = state_equal(before, cp.plot_state(cp.active_doc()))
        must(not diffs and p["layout_settings_restored"] is True, f"not restored: {diffs}")
    await case(ctx, "PL06", "P", "autocad_plot_pdf", {"path": str(PL / "layout1.pdf"), "layout": lay}, f"plot the paper-space layout {lay!r}: valid PDF, page size equals reported paper_mm, settings restored", check=chk_layout_plot, timeout=TIMEOUT, method="real-MCP-stdio+direct-COM+file")

    # ------------------------------------------------------------------ plot style
    def chk_style(p):
        info = pdf_info(PL / "monochrome.pdf", "monochrome.png")
        must(p["verified"] is True and info["header_ok"], short(p))
        must(not info["has_red_stroke"] and info["objects"] >= 3, f"monochrome.ctb should plot everything black; stroke colours {info['stroke_colors']}")
        diffs, _ = state_equal(before, cp.plot_state(cp.active_doc()))
        must(not diffs, f"style not restored: {diffs}")
    await case(ctx, "PL07", "P", "autocad_plot_pdf", {"path": str(PL / "monochrome.pdf"), "plot_style": "monochrome.ctb"}, "plot_style monochrome.ctb: the PDF has no red strokes any more (PL01 had), and the layout's style is restored", check=chk_style, timeout=TIMEOUT, method="real-MCP-stdio+direct-COM+file")

    async def bad_style():
        r = await tool(ctx, "autocad_plot_pdf", {"path": str(PL / "bad-style.pdf"), "plot_style": "no-such-style.ctb"}, label="PL08", timeout=TIMEOUT)
        diffs, _ = state_equal(before, cp.plot_state(cp.active_doc()))
        must(r["is_error"], "a style that does not exist should be refused")
        env = r["payload"].get("error", {}) if isinstance(r["payload"], dict) else {}
        must(not (PL / "bad-style.pdf").exists() and hidden_leftovers(PL) == [], f"files left: {sorted(p.name for p in PL.iterdir())}")
        must(not diffs, f"layout / plot state NOT restored after the failed plot: {diffs}")
        code = env.get("code")
        if code == "E_INTERNAL":
            observe("OBS-plot-style-error", "autocad_plot_pdf", "low", "an unknown plot_style fails as E_INTERNAL (the COM error is not classified); state was restored correctly.", short(r["payload"], 300))
        return f"refused with {code}: {env.get('message', '')[:140]}; no file, nothing left behind, settings restored"
    await acase(ctx, "PL08", "P", "autocad_plot_pdf", "an unknown plot style fails cleanly: no PDF, no temp file, every setting restored", bad_style, tool_name="autocad_plot_pdf", method="real-MCP-stdio+direct-COM+file")

    # ------------------------------------------------------------------ path rules
    def chk_rel(p):
        must((WS / "rel-plot.pdf").exists() and Path(p["file"]["path"]).resolve() == (WS / "rel-plot.pdf").resolve(), short(p["file"]))
    await case(ctx, "PL09", "R", "autocad_plot_pdf", {"path": "rel-plot.pdf"}, "a relative path is resolved against the output folder", check=chk_rel, timeout=TIMEOUT, method="real-MCP-stdio+file")
    await case(ctx, "PL10", "R", "autocad_plot_pdf", {"path": str(PL / "x.txt")}, "a .txt target is refused (E_INVALID_INPUT)", expect_error="E_INVALID_INPUT", timeout=TIMEOUT)
    await case(ctx, "PL11", "R", "autocad_plot_pdf", {"path": str(h.OUTSIDE / "x.pdf")}, "a target outside the allowed folder is refused (E_OUTPUT_PATH_REJECTED), nothing written", expect_error="E_OUTPUT_PATH_REJECTED",
               check=lambda p: must(not (h.OUTSIDE / "x.pdf").exists(), "file written outside the allowed folder"), timeout=TIMEOUT, method="real-MCP-stdio+file")
    await case(ctx, "PL12", "R", "autocad_plot_pdf", {"path": str(PL / ".." / "up.pdf")}, "a path with '..' is refused (E_OUTPUT_PATH_REJECTED)", expect_error="E_OUTPUT_PATH_REJECTED", timeout=TIMEOUT)
    await case(ctx, "PL13", "R", "autocad_plot_pdf", {"path": str(PL / "no-such-folder" / "x.pdf")}, "a missing folder gives E_FILE_NOT_FOUND", expect_error="E_FILE_NOT_FOUND", timeout=TIMEOUT)

    # ------------------------------------------------------------------ DXF export of the same drawing (independent read with ezdxf)
    dxf = EX / "plot-scratch.dxf"

    def chk_export(p):
        import ezdxf

        must(p["verified"] is True and p["document_unchanged"] is True, short(p))
        f = p["file"]
        must(f["size_bytes"] == dxf.stat().st_size and f["sha256"] == sha(dxf), "file evidence differs from disk")
        dd = ezdxf.readfile(str(dxf))
        types = sorted(e.dxftype() for e in dd.modelspace())
        must(types == ["CIRCLE", "LINE", "POLYLINE", "TEXT"], f"DXF content {types}")
        must("MCP_RED" in [l.dxf.name for l in dd.layers], "layer MCP_RED missing in the DXF")
        txt = [e for e in dd.modelspace() if e.dxftype() == "TEXT"][0]
        must(txt.dxf.text == "LIVE PLOT TEST", f"text {txt.dxf.text!r}")
    await case(ctx, "PL14", "N", "autocad_export_dxf", {"path": str(dxf)}, "export_dxf: the file re-read with ezdxf holds the circle, line, 3D polyline and text and the MCP_RED layer; SHA-256 matches", check=chk_export, timeout=TIMEOUT, method="real-MCP-stdio+file")
    await case(ctx, "PL15", "N", "autocad_export_dxf", {"path": str(dxf)}, "exporting onto an existing file is refused (E_OUTPUT_EXISTS)", expect_error="E_OUTPUT_EXISTS", timeout=TIMEOUT)
    h.dump(h.EVIDENCE / "plot_state_after.json", cp.plot_state(cp.active_doc()))
    if d.get("tolerated"):
        observe("OBS-plot-media-left-default", "autocad_plot_pdf", "low",
                "A layout whose paper (CanonicalMediaName) was never set ('') keeps a different value after autocad_plot_pdf; the result says layout_settings_restored=true and lists the key only in layout_settings_left_at_device_default.",
                "; ".join(d["tolerated"]))


async def main():
    base = cp.baseline()
    print("baseline drawings (never touched):", base)
    async with h.open_session("06_plot", env=h.server_env("com", {"AUTOCAD_MCP_COM_TIMEOUT": "120"})) as (session, log):
        ctx = Ctx(session, log, "06_plot")
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
