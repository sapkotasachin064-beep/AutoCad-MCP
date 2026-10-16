"""Process-wide session state: which backend this server is pinned to, which
drawing (if any) tool calls are pinned to, and per-call notices.

The backend is read once from AUTOCAD_MCP_BACKEND the first time it is needed
and never changes for the life of the process -- there is no automatic fallback
from the live AutoCAD backend to the headless one (see
docs/analysis/architecture-comparison.md for why).

Notices are side effects a call had that the caller did not ask for (units
changed to the configured preset, a pending AutoCAD command cancelled). They
are collected per thread for the duration of one call and returned with its
result, so nothing happens to a drawing without the result saying so.
"""

import os
import threading
import time

from core.errors import ConfigError

BACKENDS = ("com", "dxf")
DEFAULT_BACKEND = "com"

_lock = threading.Lock()
_backend_name: str | None = None
_pinned_document: str | None = None
_pinned_at: float | None = None
_started_at = time.time()
_local = threading.local()


def backend_name() -> str:
    global _backend_name
    with _lock:
        if _backend_name is None:
            raw = os.environ.get("AUTOCAD_MCP_BACKEND", DEFAULT_BACKEND).strip().lower() or DEFAULT_BACKEND
            if raw not in BACKENDS:
                raise ConfigError(
                    f"AUTOCAD_MCP_BACKEND={raw!r} is not a backend; use one of {list(BACKENDS)}. "
                    "There is no 'auto' mode: the backend is chosen explicitly so a live-drawing "
                    "session never silently turns into a headless DXF one."
                )
            _backend_name = raw
        return _backend_name


def _reset_backend_for_tests() -> None:
    global _backend_name
    with _lock:
        _backend_name = None


# ======= Units preset chosen at run time =======
#
# autocad_set_drawing_units records the preset it applied here so later
# drawing tools keep that preset instead of re-applying AUTOCAD_MCP_UNITS
# (which would flip a drawing just set to metric back to Engineering).

_units_override: str | None = None


def units_override() -> str | None:
    return _units_override


def set_units_override(preset: str | None) -> None:
    global _units_override
    with _lock:
        _units_override = preset


# ======= Document pin =======


def pinned_document() -> str | None:
    return _pinned_document


def pin_document(identity: str) -> dict:
    global _pinned_document, _pinned_at
    with _lock:
        previous = _pinned_document
        _pinned_document = identity
        _pinned_at = time.time()
    return {"pinned_document": identity, "previous_pin": previous}


def unpin_document() -> dict:
    global _pinned_document, _pinned_at
    with _lock:
        previous = _pinned_document
        _pinned_document = None
        _pinned_at = None
    return {"pinned_document": None, "previous_pin": previous}


def pin_state() -> dict:
    return {
        "pinned_document": _pinned_document,
        "pinned_since_epoch": _pinned_at,
    }


def uptime_seconds() -> float:
    return round(time.time() - _started_at, 1)


# ======= Per-call notices =======


def begin_notices() -> None:
    _local.notices = []


def add_notice(kind: str, **fields) -> None:
    notices = getattr(_local, "notices", None)
    if notices is None:  # called outside a collected call (direct library use)
        return
    notices.append({"kind": kind, **fields})


def end_notices() -> list[dict]:
    notices = getattr(_local, "notices", None) or []
    _local.notices = None
    return notices


def collect(func):
    """Run func() collecting notices; returns (result, notices)."""
    begin_notices()
    try:
        result = func()
    except BaseException:
        end_notices()
        raise
    return result, end_notices()
