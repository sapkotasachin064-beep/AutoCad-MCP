"""Step 5b - what does AutoCAD itself do when asked to highlight an entity over COM? (no MCP server involved)

HL02's first attempt saw 0 changed pixels for everything, including a persistent colour change, so the
screenshot method needed a control. This probe uses direct COM only, in a scratch drawing it creates and closes:
  E0 baseline picture
  E1 entity.Highlight(True)                 -> picture
  E2 doc.Regen(acAllViewports)              -> picture   (the server calls Regen right after Highlight)
  E3 entity.Highlight(False)                -> picture
  E4 entity.Color = 1 (no redraw call)      -> picture
  E5 doc.Regen after the colour change      -> picture   (positive control for the capture method)
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pythoncom  # noqa: E402
import win32com.client  # noqa: E402

import com_probe as cp  # noqa: E402
import mcp_harness as h  # noqa: E402
from cases import record  # noqa: E402

SHOTS = h.EVIDENCE / "highlight_probe"
SHOTS.mkdir(parents=True, exist_ok=True)


def pt(x, y, z=0.0):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, (x, y, z))


def shot(name):
    time.sleep(2.0)
    cp.print_window(SHOTS / f"{name}_pw.png")
    cp.capture_window(SHOTS / f"{name}_grab.png", bring_to_front=False)
    return {"pw": SHOTS / f"{name}_pw.png", "grab": SHOTS / f"{name}_grab.png"}


def px(a, b, name):
    out = {}
    for kind in ("pw", "grab"):
        r = cp.image_diff(a[kind], b[kind], SHOTS / f"{name}_{kind}_diff.png")
        out[kind] = r.get("changed_pixels")
    return out


base = cp.baseline()
app = cp.app()
doc = cp.retry(lambda: app.Documents.Add())
try:
    ms = cp.retry(lambda: doc.ModelSpace)
    circle = cp.retry(lambda: ms.AddCircle(pt(100, 100), 50))
    line = cp.retry(lambda: ms.AddLine(pt(0, 0), pt(200, 0)))
    cp.retry(lambda: app.ZoomExtents())
    e0 = shot("E0_baseline")
    cp.retry(lambda: circle.Highlight(True))
    e1 = shot("E1_highlight_on")
    cp.retry(lambda: doc.Regen(1))
    e2 = shot("E2_after_regen")
    cp.retry(lambda: circle.Highlight(False))
    e3 = shot("E3_highlight_off")
    cp.retry(lambda: setattr(line, "Color", 1))
    e4 = shot("E4_colour_no_redraw")
    cp.retry(lambda: doc.Regen(1))
    e5 = shot("E5_colour_after_regen")
    r = {"E0_vs_E1 highlight on": px(e0, e1, "E0_E1"),
         "E1_vs_E2 regen after highlight": px(e1, e2, "E1_E2"),
         "E0_vs_E2 highlight then regen vs baseline": px(e0, e2, "E0_E2"),
         "E0_vs_E3 highlight off": px(e0, e3, "E0_E3"),
         "E3_vs_E4 colour set, no redraw": px(e3, e4, "E3_E4"),
         "E4_vs_E5 regen after colour": px(e4, e5, "E4_E5"),
         "E3_vs_E5 colour visible after regen": px(e3, e5, "E3_E5")}
    h.dump(h.EVIDENCE / "highlight_probe.json", r)
    for k, v in r.items():
        print(f"{k}: {v}")
    sees = lambda key: max(v for v in r[key].values() if v is not None) >= 50
    record(id="HLP1", category="F", tool="autocad_highlight_entity", title="AutoCAD itself: is entity.Highlight(True) visible on screen?",
           status="PASS" if sees("E0_vs_E1 highlight on") else "FAIL", method="direct-COM+window-capture",
           evidence=f"changed pixels after Highlight(True): {r['E0_vs_E1 highlight on']}", problems=[], log_ref="highlight_probe.json")
    record(id="HLP2", category="F", tool="autocad_highlight_entity", title="AutoCAD itself: does doc.Regen (which the server calls right after Highlight) wipe the highlight?",
           status="PASS" if not sees("E0_vs_E2 highlight then regen vs baseline") else "FAIL", method="direct-COM+window-capture",
           evidence=f"vs baseline after highlight+regen: {r['E0_vs_E2 highlight then regen vs baseline']} (PASS here means the highlight SURVIVES the regen is False)",
           problems=[], log_ref="highlight_probe.json")
    record(id="HLP3", category="F", tool="autocad_highlight_entity", title="AutoCAD itself: is a colour change visible without a redraw, and after a regen?",
           status="PASS" if sees("E3_vs_E5 colour visible after regen") else "FAIL", method="direct-COM+window-capture",
           evidence=f"no redraw: {r['E3_vs_E4 colour set, no redraw']}; after regen: {r['E3_vs_E5 colour visible after regen']}", problems=[], log_ref="highlight_probe.json")
finally:
    closed = cp.close_new_docs(base)
    print("cleanup closed:", closed)
