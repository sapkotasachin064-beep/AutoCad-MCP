"""Output and drawing analysis over COM: layouts, DXF export, PDF plotting,
plus saving a full drawing scan into the local SQLite cache and counting text
patterns.

Merged from output.py and analysis.py in the minimal-architecture refactor.
"""


# ======= output.py =======
import os
import re
import uuid

import pywintypes

from backends import com_engine as cad_engine
from backends.com_engine import _retry_com, com_initialized, get_connected_app, get_drawing_identity
from core.errors import CadError, VerificationError
from core.evidence import file_evidence
from core.paths import output_path
from tools.common import as_list, read

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


# ======= analysis.py =======
from collections import Counter


from core import db
from backends.com_engine import get_active_document
from core.evidence import validate_limit
from utils import geometry
from utils.constants import TEXT_OBJECT_NAMES, get_db_path


def _read_properties(entity, object_name: str) -> dict | None:
    """Best-effort property extraction. Returns None if even the entity's
    own type-specific properties can't be read (treated by the caller as an
    inaccessible entity, not a fatal scan error)."""
    try:
        if object_name == "AcDbLine":
            start = entity.StartPoint
            end = entity.EndPoint
            return {"start_point": [start[0], start[1], start[2]], "end_point": [end[0], end[1], end[2]]}
        if object_name == "AcDbCircle":
            center = entity.Center
            return {"center": [center[0], center[1], center[2]], "radius": entity.Radius}
        if object_name in ("AcDb3dPolyline", "AcDbPolyline"):
            coords = list(entity.Coordinates)
            divisor = 3 if object_name == "AcDb3dPolyline" else 2
            vertex_count = len(coords) // divisor if divisor else 0
            return {"vertex_count": vertex_count, "closed": bool(entity.Closed)}
        if object_name in TEXT_OBJECT_NAMES:
            text = entity.TextString
            point = entity.InsertionPoint
            return {
                "text": text,
                "insertion_point": [point[0], point[1], point[2]],
                "height": entity.Height,
            }
    except pywintypes.com_error:
        return None
    return {}


def scan_all_entities() -> dict:
    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app, for_write=False)
        model_space = _retry_com(lambda: doc.ModelSpace)
        count = _retry_com(lambda: model_space.Count)

        entities = []
        skipped_count = 0
        for i in range(count):
            try:
                entity = _retry_com(lambda: model_space.Item(i))
                object_name = _retry_com(lambda: entity.ObjectName)
                handle = _retry_com(lambda: entity.Handle)
                layer = _retry_com(lambda: entity.Layer)
            except pywintypes.com_error:
                skipped_count += 1
                continue

            properties = _read_properties(entity, object_name)
            if properties is None:
                skipped_count += 1
                continue

            entities.append(
                {"handle": handle, "object_name": object_name, "layer": layer, "properties": properties}
            )

        identity = get_drawing_identity(doc)
        db_path = get_db_path()
        with db.connection(db_path) as conn:
            drawing_id = db.upsert_drawing(conn, identity.identity, identity.name, identity.path, identity.saved)
            db.replace_drawing_entities(conn, drawing_id, entities)

        type_counts = dict(Counter(e["object_name"] for e in entities))
        return {
            "status": "ok",
            "drawing_identity": identity.identity,
            "scanned_count": len(entities),
            "skipped_count": skipped_count,
            "entity_type_counts": type_counts,
            "db_path": db_path,
            "scope_note": "top-level ModelSpace entities only; block references and PaperSpace are not scanned.",
            "message": f"Scanned {len(entities)} entities ({skipped_count} inaccessible/skipped) into {db_path}.",
        }


def count_text_patterns(pattern: str, use_regex: bool = False, limit: int = 500) -> dict:
    """Count every matching TEXT/MTEXT entity; list at most `limit` of them
    (match_count is always the full count, `truncated` says if the list was
    cut)."""
    pattern = geometry.validate_text(pattern, "pattern")
    if not pattern:
        raise geometry.ValidationError("pattern must not be empty")
    limit = validate_limit(limit, default=500, maximum=10000)
    compiled = None
    if use_regex:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise geometry.ValidationError(f"pattern is not a valid regex: {exc}") from exc

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app, for_write=False)
        model_space = _retry_com(lambda: doc.ModelSpace)
        count = _retry_com(lambda: model_space.Count)

        matches = []
        for i in range(count):
            try:
                entity = _retry_com(lambda: model_space.Item(i))
                object_name = _retry_com(lambda: entity.ObjectName)
            except pywintypes.com_error:
                continue
            if object_name not in TEXT_OBJECT_NAMES:
                continue
            try:
                text = _retry_com(lambda: entity.TextString)
                layer = _retry_com(lambda: entity.Layer)
                handle = _retry_com(lambda: entity.Handle)
            except pywintypes.com_error:
                continue

            is_match = bool(compiled.search(text)) if compiled else (pattern in text)
            if is_match:
                matches.append({"handle": handle, "text": text, "layer": layer})

        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "pattern": pattern,
            "use_regex": use_regex,
            "match_count": len(matches),
            "matches": matches[:limit],
            "truncated": len(matches) > limit,
            "drawing_identity": identity.identity,
            "message": f"{len(matches)} text entity(ies) match {pattern!r} ({'regex' if use_regex else 'literal substring'}).",
        }
