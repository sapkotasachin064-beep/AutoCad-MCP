"""Direct COM access to the running AutoCAD (pywin32), independent of the MCP server.

Used ONLY to
  * read back what the MCP tools claim (layer flags, entity colour, geometry, layout settings ...),
  * simulate a user clicking another drawing tab (Activate) for the pinning test,
  * close the scratch drawings this campaign created and, at the very end, quit the AutoCAD this
    campaign started.
It never launches AutoCAD (GetActiveObject only) and never opens any file.
"""

from __future__ import annotations

import json
import subprocess
import time

import pythoncom  # noqa: F401  (importing it initialises COM for this thread)
import pywintypes
import win32com.client

RPC_BUSY = -2147418111  # RPC_E_CALL_REJECTED: AutoCAD is busy, try again


def retry(fn, attempts: int = 40, delay: float = 0.5):
    last = None
    for _ in range(attempts):
        try:
            return fn()
        except pywintypes.com_error as exc:
            if exc.args and exc.args[0] == RPC_BUSY:
                last = exc
                time.sleep(delay)
                continue
            raise
        except AttributeError as exc:  # transient late-binding failure while AutoCAD is busy
            last = exc
            time.sleep(delay)
    raise last


def app():
    """The running AutoCAD Application object. Raises if AutoCAD is not running (never launches it)."""
    return retry(lambda: win32com.client.GetActiveObject("AutoCAD.Application"))


def acad_pids(name: str = "acad.exe") -> list[int]:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, timeout=20).stdout
    pids = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].strip('"').lower() == name.lower():
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


def is_running() -> bool:
    return bool(acad_pids())


def tup(value) -> tuple:
    return tuple(float(v) for v in value)


# ----------------------------------------------------------------------------- documents


def doc_list() -> list[dict]:
    a = app()
    active = retry(lambda: a.ActiveDocument.Name) if retry(lambda: a.Documents.Count) else None
    rows = []
    for i in range(retry(lambda: a.Documents.Count)):
        doc = retry(lambda i=i: a.Documents.Item(i))
        rows.append({
            "name": retry(lambda: doc.Name),
            "full_name": retry(lambda: doc.FullName),
            "saved_flag": bool(retry(lambda: doc.Saved)),
            "read_only": bool(retry(lambda: doc.ReadOnly)),
            "active": retry(lambda: doc.Name) == active,
            "model_space_count": retry(lambda: doc.ModelSpace.Count),
        })
    return rows


def doc_count() -> int:
    return int(retry(lambda: app().Documents.Count))


def find_doc(*, name: str | None = None, full_name: str | None = None):
    a = app()
    for i in range(retry(lambda: a.Documents.Count)):
        doc = retry(lambda i=i: a.Documents.Item(i))
        if full_name is not None and retry(lambda: doc.FullName).lower() == full_name.lower():
            return doc
        if name is not None and retry(lambda: doc.Name).lower() == name.lower():
            return doc
    return None


def active_doc():
    return retry(lambda: app().ActiveDocument)


def active_name() -> str | None:
    a = app()
    return retry(lambda: a.ActiveDocument.Name) if retry(lambda: a.Documents.Count) else None


def activate(doc) -> None:
    """Simulates the user clicking another drawing tab."""
    retry(lambda: doc.Activate())


def close_doc(doc, save: bool = False) -> None:
    retry(lambda: doc.Close(save))


def baseline() -> list[dict]:
    return [{"name": d["name"], "full_name": d["full_name"]} for d in doc_list()]


def close_new_docs(base: list[dict]) -> list[str]:
    """Close (discard changes) every open drawing that was not open in `base`. Returns their names."""
    known = {(b["name"].lower(), b["full_name"].lower()) for b in base}
    closed = []
    a = app()
    for _ in range(50):
        victim = None
        for i in range(retry(lambda: a.Documents.Count)):
            doc = retry(lambda i=i: a.Documents.Item(i))
            key = (retry(lambda: doc.Name).lower(), retry(lambda: doc.FullName).lower())
            if key not in known:
                victim = doc
                break
        if victim is None:
            break
        name = retry(lambda: victim.Name)
        retry(lambda: victim.Close(False))
        closed.append(name)
    return closed


# ----------------------------------------------------------------------------- variables and entities


def sysvar(doc, name: str):
    try:
        return retry(lambda: doc.GetVariable(name))
    except pywintypes.com_error as exc:
        return f"<com_error {exc.args[0] if exc.args else exc}>"


def entity(doc, handle: str):
    return retry(lambda: doc.HandleToObject(handle))


def entity_exists(doc, handle: str) -> bool:
    try:
        entity(doc, handle)
        return True
    except pywintypes.com_error:
        return False


def _r(value, nd: int = 9):
    return tuple(round(float(v), nd) for v in value)


def describe(e) -> dict:
    """Independent read of an entity: type, layer, colour and the geometry that matters."""
    name = retry(lambda: e.ObjectName)
    out = {"object_name": name, "handle": retry(lambda: e.Handle), "layer": retry(lambda: e.Layer),
           "color": retry(lambda: e.Color)}
    if name == "AcDbLine":
        out.update(start=_r(retry(lambda: e.StartPoint)), end=_r(retry(lambda: e.EndPoint)),
                   length=round(retry(lambda: e.Length), 9))
    elif name == "AcDbCircle":
        out.update(center=_r(retry(lambda: e.Center)), radius=retry(lambda: e.Radius), area=retry(lambda: e.Area))
    elif name == "AcDbArc":
        out.update(center=_r(retry(lambda: e.Center)), radius=retry(lambda: e.Radius),
                   start_angle=retry(lambda: e.StartAngle), end_angle=retry(lambda: e.EndAngle))
    elif name == "AcDbPolyline":
        out.update(coords=_r(retry(lambda: e.Coordinates)), closed=bool(retry(lambda: e.Closed)),
                   length=retry(lambda: e.Length), area=retry(lambda: e.Area))
    elif name == "AcDb3dPolyline":
        out.update(coords=_r(retry(lambda: e.Coordinates)), closed=bool(retry(lambda: e.Closed)),
                   length=retry(lambda: e.Length))
    elif name in ("AcDbText", "AcDbMText"):
        out.update(text=retry(lambda: e.TextString), height=retry(lambda: e.Height),
                   insertion=_r(retry(lambda: e.InsertionPoint)))
    elif name == "AcDbHatch":
        out.update(pattern=retry(lambda: e.PatternName), area=retry(lambda: e.Area))
    elif "Dimension" in name:
        out.update(measurement=retry(lambda: e.Measurement))
    elif name == "AcDbBlockReference":
        out.update(block=retry(lambda: e.Name), insertion=_r(retry(lambda: e.InsertionPoint)))
    return out


def model_entities(doc) -> list[dict]:
    space = retry(lambda: doc.ModelSpace)
    rows = []
    for i in range(retry(lambda: space.Count)):
        e = retry(lambda i=i: space.Item(i))
        rows.append(describe(e))
    return rows


def model_counts(doc) -> dict:
    rows = model_entities(doc)
    by_type, by_layer = {}, {}
    for r in rows:
        by_type[r["object_name"]] = by_type.get(r["object_name"], 0) + 1
        by_layer[r["layer"]] = by_layer.get(r["layer"], 0) + 1
    return {"total": len(rows), "by_type": by_type, "by_layer": by_layer}


def layer_props(doc, name: str) -> dict | None:
    try:
        layer = retry(lambda: doc.Layers.Item(name))
    except pywintypes.com_error:
        return None
    return {
        "name": retry(lambda: layer.Name),
        "on": bool(retry(lambda: layer.LayerOn)),
        "frozen": bool(retry(lambda: layer.Freeze)),
        "locked": bool(retry(lambda: layer.Lock)),
        "color": retry(lambda: layer.Color),
        "linetype": retry(lambda: layer.Linetype),
        "lineweight": retry(lambda: layer.Lineweight),
        "plottable": bool(retry(lambda: layer.Plottable)),
    }


def all_layer_props(doc) -> list[dict]:
    rows = []
    for i in range(retry(lambda: doc.Layers.Count)):
        layer = retry(lambda i=i: doc.Layers.Item(i))
        rows.append(layer_props(doc, retry(lambda: layer.Name)))
    return rows


def linetype_names(doc) -> list[str]:
    return [retry(lambda i=i: doc.Linetypes.Item(i).Name) for i in range(retry(lambda: doc.Linetypes.Count))]


def layout_names(doc) -> list[str]:
    return [retry(lambda i=i: doc.Layouts.Item(i).Name) for i in range(retry(lambda: doc.Layouts.Count))]


def layout_by_name(doc, name: str):
    for i in range(retry(lambda: doc.Layouts.Count)):
        lo = retry(lambda i=i: doc.Layouts.Item(i))
        if retry(lambda: lo.Name).lower() == name.lower():
            return lo
    return None


LAYOUT_KEYS = ("ConfigName", "CanonicalMediaName", "PlotType", "UseStandardScale", "StandardScale", "CenterPlot",
               "StyleSheet", "PlotRotation")


def layout_settings(doc, layout_name: str = "Model") -> dict:
    lo = layout_by_name(doc, layout_name)
    out = {"layout": layout_name}
    for key in LAYOUT_KEYS:
        try:
            out[key] = retry(lambda key=key: getattr(lo, key))
        except pywintypes.com_error as exc:
            out[key] = f"<com_error {exc.args[0] if exc.args else exc}>"
    return out


def plot_state(doc) -> dict:
    """Everything the PDF plot tool promises to restore."""
    plot = retry(lambda: doc.Plot)
    return {
        "BACKGROUNDPLOT": sysvar(doc, "BACKGROUNDPLOT"),
        "QuietErrorMode": retry(lambda: plot.QuietErrorMode),
        "ActiveLayout": retry(lambda: doc.ActiveLayout.Name),
        "layouts": {n: layout_settings(doc, n) for n in layout_names(doc)},
        "doc_saved_flag": bool(retry(lambda: doc.Saved)),
    }


# ----------------------------------------------------------------------------- application


def acad_info() -> dict:
    a = app()
    info = {
        "Application.Version": retry(lambda: a.Version),
        "Application.Name": retry(lambda: a.Name),
        "Application.Caption": retry(lambda: a.Caption),
        "Application.FullName": retry(lambda: a.FullName),
        "Application.Path": retry(lambda: a.Path),
        "Application.LocaleId": retry(lambda: a.LocaleId),
        "Application.Visible": retry(lambda: a.Visible),
        "Application.HWND": retry(lambda: a.HWND),
        "Documents.Count": retry(lambda: a.Documents.Count),
    }
    if info["Documents.Count"]:
        doc = retry(lambda: a.ActiveDocument)
        for var in ("ACADVER", "_VERNUM", "PRODUCT", "RELEASE", "PROGRAM", "PLATFORM",
                    "MEASUREMENT", "INSUNITS", "LUNITS", "BACKGROUNDPLOT", "FILEDIA", "CMDDIA"):
            info[f"var.{var}"] = sysvar(doc, var)
    return info


def quit_app() -> None:
    retry(lambda: app().Quit())


# ----------------------------------------------------------------------------- window capture (best effort evidence)


def capture_window(path, bring_to_front: bool = True) -> dict:
    """Save a PNG of AutoCAD's main window (screen pixels of its rectangle). Evidence only; may fail."""
    import ctypes

    import win32con
    import win32gui
    from PIL import ImageGrab

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
    hwnd = int(retry(lambda: app().HWND))
    info = {"hwnd": hwnd}
    if bring_to_front:
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        except Exception as exc:  # Windows may refuse to steal focus
            info["foreground_error"] = repr(exc)
        time.sleep(0.8)
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    info["rect"] = [left, top, right, bottom]
    img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    img.save(path)
    info.update(path=str(path), size=list(img.size))
    return info


def print_window(path) -> dict:
    """PrintWindow capture of AutoCAD's main window (works even when other windows cover it)."""
    import ctypes

    import win32gui
    import win32ui
    from PIL import Image

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
    hwnd = int(retry(lambda: app().HWND))
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, hgt = right - left, bottom - top
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc = win32ui.CreateDCFromHandle(hwnd_dc)
    save = mfc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc, w, hgt)
    save.SelectObject(bmp)
    ok = ctypes.windll.user32.PrintWindow(hwnd, save.GetSafeHdc(), 2)  # PW_RENDERFULLCONTENT
    info = bmp.GetInfo()
    bits = bmp.GetBitmapBits(True)
    img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1)
    img.save(path)
    win32gui.DeleteObject(bmp.GetHandle())
    save.DeleteDC()
    mfc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    return {"path": str(path), "ok": bool(ok), "size": list(img.size), "rect": [left, top, right, bottom]}


def image_diff(path_a, path_b, diff_path=None, threshold: int = 40) -> dict:
    """Count pixels that differ between two PNGs of the same size (sum of channel differences > threshold)."""
    from PIL import Image, ImageChops

    a, b = Image.open(path_a).convert("RGB"), Image.open(path_b).convert("RGB")
    if a.size != b.size:
        return {"same_size": False, "size_a": list(a.size), "size_b": list(b.size)}
    diff = ImageChops.difference(a, b)
    gray = diff.convert("L").point(lambda v: 255 if v > threshold // 3 else 0)
    changed = sum(1 for v in gray.getdata() if v)
    bbox = gray.getbbox()
    if diff_path:
        gray.save(diff_path)
    return {"same_size": True, "size": list(a.size), "changed_pixels": changed, "changed_bbox": list(bbox) if bbox else None}


def dumps(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
