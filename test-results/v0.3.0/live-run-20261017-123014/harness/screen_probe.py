"""Can we take a picture of the AutoCAD window? Tries PrintWindow (works while covered) and a screen grab."""

import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import com_probe as cp  # noqa: E402
import mcp_harness as h  # noqa: E402

import win32con  # noqa: E402
import win32gui  # noqa: E402
import win32ui  # noqa: E402
from PIL import Image  # noqa: E402

ctypes.windll.user32.SetProcessDPIAware()
hwnd = int(cp.retry(lambda: cp.app().HWND))
left, top, right, bottom = win32gui.GetWindowRect(hwnd)
w, hgt = right - left, bottom - top
print("hwnd", hwnd, "rect", (left, top, right, bottom), "size", (w, hgt), "iconic", win32gui.IsIconic(hwnd), "visible", win32gui.IsWindowVisible(hwnd))


def print_window(path):
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
    return ok, img.size


print("PrintWindow:", print_window(h.EVIDENCE / "screen_probe_printwindow.png"))
print("grab:", cp.capture_window(h.EVIDENCE / "screen_probe_grab.png", bring_to_front=True))
