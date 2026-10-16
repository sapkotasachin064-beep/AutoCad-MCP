"""Layouts, DXF export and PDF plotting over COM (V0.3.0).

DXF export uses Document.Export, not SaveAs: SaveAs re-points the open
drawing at the new file, Export writes a copy and leaves the drawing's name
and path alone. Behaviour of Export relied on here (documented by a reference
implementation measured on AutoCAD 2026, docs/analysis/architecture-comparison.md):
the extension argument is "DXF" without a dot, the file is written as
<base>.DXF, unsaved drawings export, and the whole drawing (model space,
layouts, blocks) is written whatever the selection set holds -- the set is
only there because the ActiveX signature requires one. The export goes to a
temporary name in the target folder and replaces the target only on success.

PDF plotting forces BACKGROUNDPLOT=0 for the duration of the call (a
background plot returns before the file exists), turns on the plot object's
QuietErrorMode so a plot error cannot open a modal dialog, applies the
requested device / paper / area to the layout, and restores every layout
setting and system variable it touched afterwards. The PDF is verified on
disk: it exists, starts with %PDF, and its first /MediaBox is reported in mm.

Neither has been run against a live AutoCAD in this project yet.
"""

import os
import re
import uuid

import pywintypes

import cad_engine
from cad_engine import _retry_com, com_initialized, get_connected_app, get_drawing_identity
from core.errors import CadError, VerificationError
from core.evidence import file_evidence
from core.paths import output_path
from tools._common import as_list, read

AC_SELECTION_SET_ALL = 5
AC_PLOT_EXTENTS = 1
AC_PLOT_LAYOUT = 5
AC_SCALE_TO_FIT = 0
AC_SCALE_1_1 = 16
PDF_DEVICE = "DWG To PDF.pc3"
_LAYOUT_SETTINGS = ("ConfigName", "CanonicalMediaName", "PlotType", "UseStandardScale", "StandardScale",
                    "CenterPlot", "StyleSheet")


def _layouts(doc):
    layouts = doc.Layouts
    for i in range(_retry_com(lambda: layouts.Count)):
        yield _retry_com(lambda i=i: layouts.Item(i))


def list_layouts() -> dict:
    with com_initialized():
        doc = cad_engine.get_active_document(get_connected_app(), for_write=False)
        current = read(read(doc, "ActiveLayout"), "Name")
        rows = []
        for layout in _layouts(doc):
            rows.append({
                "name": read(layout, "Name"),
                "is_model": bool(read(layout, "ModelType", False)),
                "tab_order": read(layout, "TabOrder"),
                "plot_device": read(layout, "ConfigName"),
                "paper": read(layout, "CanonicalMediaName"),
                "plot_style": read(layout, "StyleSheet"),
                "plot_type": read(layout, "PlotType"),
                "current": read(layout, "Name") == current,
            })
        rows.sort(key=lambda r: (r["tab_order"] is None, r["tab_order"]))
        return {"status": "ok", "count": len(rows), "layouts": rows, "current_layout": current,
                "drawing_identity": get_drawing_identity(doc).identity}


def export_dxf(path: str, overwrite: bool = False) -> dict:
    target = output_path(path, suffixes=(".dxf",), overwrite=overwrite)
    with com_initialized():
        doc = cad_engine.get_active_document(get_connected_app(), for_write=False)
        before = get_drawing_identity(doc)
        temp_base = target.with_name(f".{target.stem}.{uuid.uuid4().hex[:8]}")
        written = None
        selection = _retry_com(lambda: doc.SelectionSets.Add(f"MCP_EXPORT_{uuid.uuid4().hex[:8]}"))
        try:
            _retry_com(lambda: selection.Select(AC_SELECTION_SET_ALL))
            try:
                _retry_com(lambda: doc.Export(str(temp_base), "DXF", selection))
            except pywintypes.com_error as exc:
                raise RuntimeError(f"AutoCAD could not export DXF: {exc}") from exc
            for candidate in (f"{temp_base}.DXF", f"{temp_base}.dxf"):
                if os.path.isfile(candidate):
                    written = candidate
                    break
            if written is None:
                raise VerificationError(f"Export reported success but no file appeared at {temp_base}.DXF")
            os.replace(written, target)
        finally:
            try:
                _retry_com(lambda: selection.Delete())
            except pywintypes.com_error:
                pass
            for leftover in (f"{temp_base}.DXF", f"{temp_base}.dxf"):
                if os.path.exists(leftover):
                    os.remove(leftover)
        after = get_drawing_identity(doc)
        with open(target, "rb") as fh:
            head = fh.read(64)
        looks_dxf = b"SECTION" in head
        evidence = file_evidence(target)
        return {
            "status": "ok",
            "file": evidence,
            "drawing_identity": after.identity,
            "document_unchanged": after.identity == before.identity,
            "verified": looks_dxf and evidence["size_bytes"] > 0 and after.identity == before.identity,
            "verification": "file_on_disk_dxf_header_and_document_identity_unchanged",
            "message": f"Exported a DXF copy to {target}; the open drawing is unchanged.",
        }


def _pdf_mediabox_mm(path) -> list | None:
    with open(path, "rb") as fh:
        data = fh.read(2_000_000)
    match = re.search(rb"/MediaBox\s*\[\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*\]", data)
    if not match:
        return None
    x0, y0, x1, y1 = (float(v) for v in match.groups())
    return [round((x1 - x0) * 25.4 / 72.0, 1), round((y1 - y0) * 25.4 / 72.0, 1)]


def _match_media(layout, paper: str) -> str:
    names = [str(n) for n in as_list(_retry_com(lambda: layout.GetCanonicalMediaNames()))]
    wanted = paper.strip().lower()
    exact = [n for n in names if n.lower() == wanted]
    partial = [n for n in names if wanted in n.lower()]
    if exact:
        return exact[0]
    if len(partial) == 1:
        return partial[0]
    raise CadError(
        f"paper {paper!r} {'is ambiguous' if partial else 'is not offered by ' + PDF_DEVICE}; "
        f"pick one of the listed canonical media names",
        code="E_INVALID_INPUT",
        details={"candidates": (partial or names)[:40]},
    )


def plot_pdf(path: str, layout: str | None = None, paper: str | None = None, plot_style: str | None = None,
             overwrite: bool = False) -> dict:
    """layout=None plots model space to its extents, scaled to fit the paper;
    a named paper-space layout is plotted as laid out at 1:1."""
    target = output_path(path, suffixes=(".pdf",), overwrite=overwrite)
    with com_initialized():
        doc = cad_engine.get_active_document(get_connected_app(), for_write=False)
        cad_engine.clear_pending_command(doc)
        if layout is None:
            plot_layout = _retry_com(lambda: doc.ModelSpace.Layout)
        else:
            plot_layout = next((lo for lo in _layouts(doc) if str(read(lo, "Name")).lower() == layout.lower()), None)
            if plot_layout is None:
                raise CadError(f"Layout {layout!r} not found.", code="E_LAYOUT_NOT_FOUND",
                               details={"layouts": [read(lo, "Name") for lo in _layouts(doc)]})
        is_model = bool(read(plot_layout, "ModelType", False))
        previous_layout = _retry_com(lambda: doc.ActiveLayout)
        saved_settings = {k: read(plot_layout, k) for k in _LAYOUT_SETTINGS}
        old_background = cad_engine._get_variable(doc, "BACKGROUNDPLOT")
        plot = _retry_com(lambda: doc.Plot)
        old_quiet = read(plot, "QuietErrorMode")
        # Plot to a temporary name and replace the target only once a PDF exists,
        # so a failed plot never destroys a previous file (overwrite=True).
        temp = target.with_name(f".{target.stem}.{uuid.uuid4().hex[:8]}.pdf")
        not_restored = {}
        left_at_default = []
        try:
            if old_background not in (None, 0):
                _retry_com(lambda: doc.SetVariable("BACKGROUNDPLOT", 0))
            if old_quiet is not None:
                _retry_com(lambda: setattr(plot, "QuietErrorMode", True))
            _retry_com(lambda: setattr(doc, "ActiveLayout", plot_layout))
            _retry_com(lambda: plot_layout.RefreshPlotDeviceInfo())
            _retry_com(lambda: setattr(plot_layout, "ConfigName", PDF_DEVICE))
            _retry_com(lambda: plot_layout.RefreshPlotDeviceInfo())
            if paper:
                media = _match_media(plot_layout, paper)
                _retry_com(lambda: setattr(plot_layout, "CanonicalMediaName", media))
            if plot_style:
                _retry_com(lambda: setattr(plot_layout, "StyleSheet", plot_style))
            if is_model:
                _retry_com(lambda: setattr(plot_layout, "PlotType", AC_PLOT_EXTENTS))
                _retry_com(lambda: setattr(plot_layout, "UseStandardScale", True))
                _retry_com(lambda: setattr(plot_layout, "StandardScale", AC_SCALE_TO_FIT))
                _retry_com(lambda: setattr(plot_layout, "CenterPlot", True))
            else:
                _retry_com(lambda: setattr(plot_layout, "PlotType", AC_PLOT_LAYOUT))
                _retry_com(lambda: setattr(plot_layout, "UseStandardScale", True))
                _retry_com(lambda: setattr(plot_layout, "StandardScale", AC_SCALE_1_1))
            try:
                plotted = _retry_com(lambda: plot.PlotToFile(str(temp), PDF_DEVICE))
            except pywintypes.com_error as exc:
                raise CadError(f"AutoCAD could not plot to {target}: {exc}", code="E_PLOT_FAILED") from exc
            if not plotted:
                raise CadError("PlotToFile returned False: AutoCAD refused the plot (check the layout's plot "
                               f"area and the {PDF_DEVICE!r} device).", code="E_PLOT_FAILED")
        finally:
            for key, value in saved_settings.items():
                if value is None:
                    continue
                if key == "CanonicalMediaName" and value == "":
                    # A layout that never had paper chosen reports ''. AutoCAD rejects ''
                    # as input ("Invalid input", seen live on 2024), so the restored
                    # device's default paper applies instead; say so rather than fail.
                    left_at_default.append(key)
                    continue
                try:
                    if key == "ConfigName":
                        _retry_com(lambda value=value: setattr(plot_layout, "ConfigName", value))
                        _retry_com(lambda: plot_layout.RefreshPlotDeviceInfo())
                    elif key == "CenterPlot" and saved_settings.get("PlotType") == AC_PLOT_LAYOUT:
                        continue  # CenterPlot cannot be set while PlotType is acLayout
                    else:
                        _retry_com(lambda key=key, value=value: setattr(plot_layout, key, value))
                except pywintypes.com_error as exc:
                    not_restored[key] = str(exc)
            try:
                if old_background not in (None, 0):
                    _retry_com(lambda: doc.SetVariable("BACKGROUNDPLOT", old_background))
                if old_quiet is not None:
                    _retry_com(lambda: setattr(plot, "QuietErrorMode", old_quiet))
                _retry_com(lambda: setattr(doc, "ActiveLayout", previous_layout))
            except pywintypes.com_error as exc:
                not_restored["plot_session_state"] = str(exc)

        if not os.path.isfile(temp) or os.path.getsize(temp) == 0:
            if os.path.exists(temp):
                os.remove(temp)
            raise CadError(f"PlotToFile reported success but wrote no file at {temp}.", code="E_PLOT_FAILED")
        with open(temp, "rb") as fh:
            is_pdf = fh.read(5) == b"%PDF-"
        if not is_pdf:
            os.remove(temp)
            raise VerificationError(f"The plot output at {temp} is not a PDF; the target was left untouched.")
        os.replace(temp, target)
        return {
            "status": "ok",
            "file": file_evidence(target),
            "layout": read(plot_layout, "Name"),
            "model_space": is_model,
            "device": PDF_DEVICE,
            "paper_mm": _pdf_mediabox_mm(target),
            "layout_settings_restored": not not_restored,
            "layout_settings_not_restored": not_restored,
            "layout_settings_left_at_device_default": left_at_default,
            "drawing_identity": get_drawing_identity(doc).identity,
            "verified": is_pdf,
            "verification": "pdf_on_disk_with_pdf_header",
            "message": f"Plotted {'model space' if is_model else read(plot_layout, 'Name')} to {target}.",
        }
