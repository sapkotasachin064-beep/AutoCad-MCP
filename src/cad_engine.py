"""AutoCAD COM connection: install/running detection, launch, readiness,
VARIANT conversion, and drawing identity.

MCP tool handlers can run on a worker thread that never called CoInitialize,
which makes every win32com call fail with
(-2147221008, 'CoInitialize has not been called.'). Every public entry
point here wraps its COM work in `com_initialized()` so the calling thread
is always COM-initialized for that call, paired with CoUninitialize.
"""

import os
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

from core import session
from core.errors import CadStateError
from domain import units
from utils.constants import MIN_SUPPORTED_RELEASE, RELEASE_TO_YEAR

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
    """Return a verified, ready COM Application object, or raise
    CadStateError (a RuntimeError). Caller must already be inside a
    com_initialized() context (drawing.py's public entry points provide one)."""
    app = get_running_instance()
    if app is None:
        raise CadStateError(
            "AutoCAD is not running. Call autocad_launch_application first.",
            code="E_AUTOCAD_NOT_RUNNING",
        )
    status = verify_connection(app)
    if not status.connected:
        raise CadStateError(status.message, code="E_AUTOCAD_NOT_RESPONDING")
    if not status.supported:
        raise CadStateError(
            status.message, code="E_AUTOCAD_UNSUPPORTED_RELEASE", details={"version": status.version}
        )
    return app


def get_active_document(app, *, for_write: bool = True):
    """Return the ActiveDocument, or raise CadStateError (a RuntimeError).
    Caller must already be inside a com_initialized() context.

    Every tool reaches the drawing through here, so this is where the
    document pin is enforced (a pinned session refuses to touch any other
    drawing). for_write=True (the default, and the only V0.2.x behaviour) is
    for tools that change the drawing: a command left pending at AutoCAD's
    command line is cancelled and the configured units preset is applied --
    each only when needed, and each reported as a notice. for_write=False is
    for read-only tools, which never send keystrokes or change variables."""
    count = _retry_com(lambda: app.Documents.Count)
    if count == 0:
        raise CadStateError(
            "No document is open in AutoCAD. Call autocad_create_new_drawing or open a drawing first.",
            code="E_NO_ACTIVE_DOCUMENT",
        )
    doc = _retry_com(lambda: app.ActiveDocument)
    check_pinned_document(doc)
    if for_write:
        clear_pending_command(doc)
        apply_units_policy(doc)
    else:
        note_active_command(doc)
    return doc


def check_pinned_document(doc) -> None:
    pinned = session.pinned_document()
    if pinned is None:
        return
    actual = get_drawing_identity(doc).identity
    if actual != pinned:
        raise CadStateError(
            f"The active drawing is {actual!r}, but this session is pinned to {pinned!r}. "
            "Nothing was changed.",
            code="E_DOCUMENT_CHANGED",
            details={"pinned_document": pinned, "active_document": actual},
        )


# ======= Units policy =======
#
# V0.2.3 forced Engineering units (LUNITS=3, LUPREC=4, INSUNITS=1,
# MEASUREMENT=0) on every active document before every tool, read-only ones
# included. Since V0.3.0 the preset comes from AUTOCAD_MCP_UNITS
# (domain/units.py; default still "engineering"), is applied only by tools
# that change the drawing, skips variables that already have the preset's
# value (so an already-correct drawing is not marked modified), and reports
# every change as a "units_changed" notice. AutoCAD's LUNITS=2 is Decimal,
# not Engineering (LUNITS=3); MEASUREMENT=0 is the Imperial acad.* library,
# MEASUREMENT=1 the Metric acadiso.* one.

_ENGINEERING_UNITS_VARS = units.UNIT_PRESETS["engineering"]


def _get_variable(doc, name: str):
    getter = getattr(doc, "GetVariable", None)
    if getter is None:
        return None
    try:
        return _retry_com(lambda: getter(name))
    except (pywintypes.com_error, AttributeError):
        return None


def _apply_variables(doc, variables) -> tuple[dict, dict]:
    changed, failed = {}, {}
    for name, value in variables:
        current = _get_variable(doc, name)
        if current is not None and current == value:
            continue
        try:
            _retry_com(lambda name=name, value=value: doc.SetVariable(name, value))
            changed[name] = {"from": current, "to": value}
        except (pywintypes.com_error, AttributeError) as exc:
            failed[name] = str(exc)
    return changed, failed


def apply_units_policy(doc) -> None:
    """Apply the AUTOCAD_MCP_UNITS preset, best-effort (never fatal to the
    tool call that triggered it) and reported as a notice when it changed or
    failed to change anything."""
    preset = units.preset_name()
    changed, failed = _apply_variables(doc, units.preset_variables(preset))
    if changed:
        session.add_notice("units_changed", preset=preset, variables=changed)
    if failed:
        session.add_notice("units_not_applied", preset=preset, errors=failed)


def set_engineering_units(doc) -> None:
    """Force the Engineering preset on doc regardless of AUTOCAD_MCP_UNITS
    (the V0.2.3 helper, kept for direct callers). Best-effort."""
    _apply_variables(doc, _ENGINEERING_UNITS_VARS)


def read_insunits(doc) -> int | None:
    value = _get_variable(doc, "INSUNITS")
    return int(value) if value is not None else None


def _command_active(doc) -> int | None:
    value = _get_variable(doc, "CMDACTIVE")
    return int(value) if value is not None else None


def note_active_command(doc) -> None:
    active = _command_active(doc)
    if active:
        session.add_notice("autocad_command_active", cmdactive=active,
                           message="A command is active in AutoCAD; it was left untouched.")


def clear_pending_command(doc) -> None:
    """Best-effort: cancel a command the user left pending at AutoCAD's
    command line (e.g. a LINE command started interactively and never
    finished) before a tool changes the drawing. Since V0.3.0, CMDACTIVE is
    read first and ESC is only sent when a command is actually active; when
    CMDACTIVE cannot be read, ESC is sent as in V0.2.x. Two ESC characters
    match the ESC ESC convention AutoCAD itself documents for SendCommand to
    back out of a nested prompt. Never raises -- a failed cancel is not
    fatal to the tool call that follows it."""
    active = _command_active(doc)
    if active == 0:
        return
    try:
        _retry_com(lambda: doc.SendCommand("\x1b\x1b"))
    except (pywintypes.com_error, AttributeError):
        return
    if active:
        session.add_notice("pending_command_cancelled", cmdactive=active)


# ======= VARIANT conversion (shared by entity creation and editing) =======


def point_variant(point: tuple[float, float, float]):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(point))


def flat_variant(values: list[float]):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(values))


# ======= Drawing identity =======
#
# AutoCAD's COM Document object has no GUID. The best stable key available is
# the saved file path -- but doc.Path is NOT a reliable "has this been saved"
# signal: verified against a live AutoCAD 2024, a brand-new unsaved document's
# Path is the process's current working directory (non-empty), not "". The
# reliable signal is doc.FullName, which is "" until the document is saved at
# least once. An unsaved drawing has no identity that survives past this
# AutoCAD session, which every caller must treat as a real limitation, not an
# edge case to paper over.


@dataclass(frozen=True)
class DrawingIdentity:
    identity: str
    name: str
    path: str | None
    saved: bool


def get_drawing_identity(doc) -> DrawingIdentity:
    name = doc.Name
    full_name = (doc.FullName or "").strip()
    if full_name:
        identity = f"path:{full_name.lower()}"
        return DrawingIdentity(identity=identity, name=name, path=full_name, saved=True)
    identity = f"unsaved:{name.lower()}"
    return DrawingIdentity(identity=identity, name=name, path=None, saved=False)


# ======= Best-effort OpenCode host detection =======
#
# Moved to core/hosts.py in V0.3.0 (pure, importable without pywin32).

from core.hosts import _OPENCODE_ENV_MARKERS, detect_opencode  # noqa: E402,F401
