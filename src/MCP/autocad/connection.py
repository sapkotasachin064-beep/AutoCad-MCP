"""AutoCAD COM connection: install/running detection, launch, readiness.

MCP tool handlers can run on a worker thread that never called CoInitialize,
which makes every win32com call fail with
(-2147221008, 'CoInitialize has not been called.'). Every public entry
point here wraps its COM work in `com_initialized()` so the calling thread
is always COM-initialized for that call, paired with CoUninitialize.
"""

import random
import re
import subprocess
import time
import winreg
from contextlib import contextmanager
from dataclasses import dataclass

import pythoncom
import pywintypes
import win32com.client

from .config import MIN_SUPPORTED_RELEASE, RELEASE_TO_YEAR

PROG_ID = "AutoCAD.Application"
PROCESS_NAME = "acad.exe"
LAUNCH_TIMEOUT_SECONDS = 60
POLL_INTERVAL_SECONDS = 1.0

RPC_E_CALL_REJECTED = -2147418111  # 0x80010001, server busy (e.g. still starting up)
RETRY_ATTEMPTS = 10
RETRY_MIN_DELAY = 0.5
RETRY_MAX_DELAY = 1.0


@contextmanager
def com_initialized():
    """CoInitialize is reference-counted per thread, so nested use (an outer
    entry point calling an inner helper that also wraps itself) is safe."""
    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


def _is_busy_error(exc: pywintypes.com_error) -> bool:
    hresult = exc.args[0] if exc.args else None
    return hresult == RPC_E_CALL_REJECTED


def _retry_com(func, attempts: int = RETRY_ATTEMPTS):
    """Retry a COM call while AutoCAD reports RPC_E_CALL_REJECTED (busy /
    still starting up). Any other com_error is not transient and raises
    immediately.

    Also retries AttributeError: verified live against AutoCAD 2024 under
    rapid sequential calls, win32com's dynamic dispatch can raise
    AttributeError (not pywintypes.com_error) for a real, existing COM
    property when GetIDsOfNames transiently fails while AutoCAD is busy --
    win32com/client/dynamic.py catches that internal pythoncom.ole_error
    itself and re-raises it as a plain AttributeError, so it would otherwise
    bypass the com_error retry below entirely.
    """
    last_exc = None
    for _ in range(attempts):
        try:
            return func()
        except pywintypes.com_error as exc:
            if not _is_busy_error(exc):
                raise
            last_exc = exc
        except AttributeError as exc:
            last_exc = exc
        time.sleep(random.uniform(RETRY_MIN_DELAY, RETRY_MAX_DELAY))
    raise last_exc


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
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"{PROG_ID}\\CurVer"):
            return True
    except FileNotFoundError:
        return False


def _is_process_running(name: str = PROCESS_NAME) -> bool:
    """COM-free process check, used to tell 'not running at all' apart from
    'process is up but COM isn't answering yet' when GetActiveObject fails."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return name.lower() in result.stdout.lower()


def get_running_instance():
    """Return the live AutoCAD COM object if one is already running, else
    None. Retries through RPC_E_CALL_REJECTED while AutoCAD is mid-startup;
    any other failure (nothing in the ROT) means it just isn't running."""
    try:
        return _retry_com(lambda: win32com.client.GetActiveObject(PROG_ID))
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
        version_string = _retry_com(lambda: app.Version)
        _retry_com(lambda: app.Documents)  # round trip past a half-started process
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
    with com_initialized():
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
            if _is_process_running():
                return AutocadStatus(
                    installed=True,
                    running=True,
                    connected=False,
                    supported=False,
                    version=None,
                    release_year=None,
                    message=f"{PROCESS_NAME} is running but not yet answering COM calls.",
                )
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
    with com_initialized():
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
            app = _retry_com(lambda: win32com.client.Dispatch(PROG_ID))
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
                    _retry_com(lambda: setattr(app, "Visible", True))
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
    """Return a verified, ready COM Application object, or raise RuntimeError.
    Caller must already be inside a com_initialized() context (drawing.py's
    public entry points provide one)."""
    app = get_running_instance()
    if app is None:
        raise RuntimeError("AutoCAD is not running. Call autocad_launch_application first.")
    status = verify_connection(app)
    if not status.connected:
        raise RuntimeError(status.message)
    if not status.supported:
        raise RuntimeError(status.message)
    return app


def get_active_document(app):
    """Return the ActiveDocument, or raise RuntimeError if none is open.
    Caller must already be inside a com_initialized() context."""
    count = _retry_com(lambda: app.Documents.Count)
    if count == 0:
        raise RuntimeError(
            "No document is open in AutoCAD. Call create_new_drawing or open a drawing first."
        )
    return _retry_com(lambda: app.ActiveDocument)
