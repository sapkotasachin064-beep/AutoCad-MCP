"""AutoCAD COM connection: install/running detection, launch, readiness."""

import re
import time
import winreg
from dataclasses import dataclass

import pywintypes
import win32com.client

from .config import MIN_SUPPORTED_RELEASE, RELEASE_TO_YEAR

PROG_ID = "AutoCAD.Application"
LAUNCH_TIMEOUT_SECONDS = 60
POLL_INTERVAL_SECONDS = 1.0


@dataclass
class AutocadStatus:
    installed: bool
    running: bool
    connected: bool
    supported: bool
    version: str | None
    release_year: int | None
    message: str


def is_installed() -> bool:
    """Registry-only check. Does not start or touch AutoCAD."""
    for hive in (winreg.HKEY_CLASSES_ROOT,):
        try:
            with winreg.OpenKey(hive, f"{PROG_ID}\\CurVer"):
                return True
        except FileNotFoundError:
            continue
    return False


def get_running_instance():
    """Return the live AutoCAD COM object if one is already running, else None."""
    try:
        return win32com.client.GetActiveObject(PROG_ID)
    except pywintypes.com_error:
        return None


def _parse_release(version_string: str) -> float | None:
    match = re.match(r"(\d+)\.(\d+)", version_string or "")
    if not match:
        return None
    return float(f"{match.group(1)}.{match.group(2)}")


def verify_connection(app) -> AutocadStatus:
    """Confirm the COM object actually answers, not just that it exists."""
    try:
        version_string = app.Version
        app.Documents  # access to force a round trip past a half-started process
    except pywintypes.com_error as exc:
        return AutocadStatus(
            installed=True,
            running=True,
            connected=False,
            supported=False,
            version=None,
            release_year=None,
            message=f"AutoCAD process found but not responding to COM calls: {exc}",
        )

    release = _parse_release(version_string)
    release_year = RELEASE_TO_YEAR.get(release)
    supported = release is not None and release >= MIN_SUPPORTED_RELEASE

    if supported:
        message = f"Connected to AutoCAD {release_year or release}."
    else:
        message = (
            f"Connected, but AutoCAD release {version_string!r} is below the minimum "
            f"supported release {MIN_SUPPORTED_RELEASE} (AutoCAD 2021)."
        )

    return AutocadStatus(
        installed=True,
        running=True,
        connected=True,
        supported=supported,
        version=version_string,
        release_year=release_year,
        message=message,
    )


def get_status() -> AutocadStatus:
    installed = is_installed()
    if not installed:
        return AutocadStatus(
            installed=False,
            running=False,
            connected=False,
            supported=False,
            version=None,
            release_year=None,
            message="AutoCAD is not installed (AutoCAD.Application ProgID not registered).",
        )

    app = get_running_instance()
    if app is None:
        return AutocadStatus(
            installed=True,
            running=False,
            connected=False,
            supported=False,
            version=None,
            release_year=None,
            message="AutoCAD is installed but not currently running.",
        )

    return verify_connection(app)


def launch_and_wait(timeout: float = LAUNCH_TIMEOUT_SECONDS) -> AutocadStatus:
    """Launch AutoCAD via COM Dispatch (attaches instead if already running),
    then poll until it answers COM calls or the timeout elapses."""
    if not is_installed():
        return AutocadStatus(
            installed=False,
            running=False,
            connected=False,
            supported=False,
            version=None,
            release_year=None,
            message="Cannot launch: AutoCAD is not installed.",
        )

    try:
        app = win32com.client.Dispatch(PROG_ID)
    except pywintypes.com_error as exc:
        return AutocadStatus(
            installed=True,
            running=False,
            connected=False,
            supported=False,
            version=None,
            release_year=None,
            message=f"Failed to launch AutoCAD via COM: {exc}",
        )

    deadline = time.monotonic() + timeout
    last_status = None
    while time.monotonic() < deadline:
        last_status = verify_connection(app)
        if last_status.connected:
            try:
                app.Visible = True
            except pywintypes.com_error:
                pass
            return last_status
        time.sleep(POLL_INTERVAL_SECONDS)

    return last_status or AutocadStatus(
        installed=True,
        running=True,
        connected=False,
        supported=False,
        version=None,
        release_year=None,
        message=f"AutoCAD did not become ready within {timeout}s.",
    )


def get_connected_app():
    """Return a verified, ready COM Application object, or raise RuntimeError."""
    app = get_running_instance()
    if app is None:
        raise RuntimeError("AutoCAD is not running. Call autocad_launch_application first.")
    status = verify_connection(app)
    if not status.connected:
        raise RuntimeError(status.message)
    if not status.supported:
        raise RuntimeError(status.message)
    return app
