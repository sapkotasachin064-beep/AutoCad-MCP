"""Document lifecycle over COM: list, open, save / save-as, close, activate,
and explicit drawing units.

Safety rules (docs/analysis/rebuild-plan.md):
  * opening defaults to read-only;
  * saving never replaces an existing file unless overwrite=True (saving a
    drawing back to its own file is a normal Save and needs no flag);
  * closing refuses to discard unsaved changes unless discard_changes=True;
  * while a document pin is set, open/activate refuse to switch drawings
    unless pin=True moves the pin.
Every result reports the drawing identity it ended up on.
"""

import os

import pywintypes

import cad_engine
from cad_engine import _retry_com, com_initialized, get_connected_app, get_drawing_identity
from core import session
from core.errors import CadError, CadStateError, VerificationError
from core.evidence import file_evidence
from core.paths import input_path, output_path
from domain import units
from tools._common import read

# AcSaveAsType (AutoCAD type library): DWG and DXF codes per release format.
SAVE_AS_TYPES = {
    "dwg": {"R2000": 12, "R2004": 24, "R2007": 36, "R2010": 48, "R2013": 60, "R2018": 64},
    "dxf": {"R2000": 13, "R2004": 25, "R2007": 37, "R2010": 49, "R2013": 61, "R2018": 65},
}
OPENABLE_SUFFIXES = (".dwg", ".dxf", ".dwt", ".dws")


def _record(doc, active_name: str | None) -> dict:
    identity = get_drawing_identity(doc)
    return {
        "name": identity.name,
        "identity": identity.identity,
        "path": identity.path,
        "saved_to_disk": identity.saved,
        "unsaved_changes": not bool(read(doc, "Saved", True)),
        "read_only": bool(read(doc, "ReadOnly", False)),
        "active": identity.name == active_name,
    }


def _documents(app) -> list:
    count = _retry_com(lambda: app.Documents.Count)
    return [_retry_com(lambda i=i: app.Documents.Item(i)) for i in range(count)]


def _active_name(app) -> str | None:
    if _retry_com(lambda: app.Documents.Count) == 0:
        return None
    return _retry_com(lambda: app.ActiveDocument.Name)


def _find(app, identity: str):
    for doc in _documents(app):
        if get_drawing_identity(doc).identity == identity:
            return doc
    raise CadError(
        f"No open drawing has identity {identity!r}.",
        code="E_DOCUMENT_NOT_FOUND",
        details={"identity": identity, "open": [get_drawing_identity(d).identity for d in _documents(app)]},
    )


def _refuse_switch_while_pinned(target_identity: str | None, pin: bool) -> str | None:
    pinned = session.pinned_document()
    if pinned is not None and not pin and target_identity != pinned:
        raise CadStateError(
            f"This session is pinned to {pinned!r}; switching drawings would break the pinned job. "
            "Pass pin=true to move the pin, or call autocad_unpin_document first.",
            code="E_DOCUMENT_PINNED",
            details={"pinned_document": pinned, "requested": target_identity},
        )
    return pinned


def list_drawings() -> dict:
    with com_initialized():
        app = get_connected_app()
        active = _active_name(app)
        drawings = [_record(doc, active) for doc in _documents(app)]
        return {
            "status": "ok",
            "count": len(drawings),
            "drawings": drawings,
            "pinned_document": session.pinned_document(),
            "message": f"{len(drawings)} drawing(s) open.",
        }


def open_drawing(path: str, read_only: bool = True, pin: bool = False) -> dict:
    resolved = input_path(path, suffixes=OPENABLE_SUFFIXES)
    target_identity = f"path:{str(resolved).lower()}"
    previous_pin = _refuse_switch_while_pinned(target_identity, pin)

    with com_initialized():
        app = get_connected_app()
        already_open = None
        for doc in _documents(app):
            if get_drawing_identity(doc).identity == target_identity:
                already_open = doc
                break
        if already_open is not None:
            _retry_com(lambda: already_open.Activate())
            doc = already_open
        else:
            try:
                doc = _retry_com(lambda: app.Documents.Open(str(resolved), bool(read_only)))
            except pywintypes.com_error as exc:
                raise RuntimeError(f"AutoCAD could not open {resolved}: {exc}") from exc

        active = _retry_com(lambda: app.ActiveDocument)
        identity = get_drawing_identity(active)
        if identity.identity != target_identity:
            raise VerificationError(
                f"Opened {resolved} but the active drawing is {identity.identity!r}.",
                details={"expected": target_identity, "active_document": identity.identity},
            )
        if pin:
            session.pin_document(identity.identity)
        record = _record(active, identity.name)
        return {
            "status": "ok",
            **record,
            "already_open": already_open is not None,
            "requested_read_only": bool(read_only),
            "pinned": bool(pin),
            "previous_pin": previous_pin,
            "verified": True,
            "verification": "active_document_identity_matches_path",
            "drawing_identity": identity.identity,
            "message": (
                f"{'Activated already-open' if already_open is not None else 'Opened'} {identity.name}"
                f"{' (read-only)' if record['read_only'] else ''}."
            ),
        }


def save_drawing(path: str | None = None, overwrite: bool = False, format: str = "dwg",
                 version: str = "R2018") -> dict:
    fmt = (format or "").strip().lower()
    if fmt not in SAVE_AS_TYPES:
        raise CadError(f"format must be one of {sorted(SAVE_AS_TYPES)}, got {format!r}", code="E_INVALID_INPUT")
    if version not in SAVE_AS_TYPES[fmt]:
        raise CadError(f"version must be one of {sorted(SAVE_AS_TYPES[fmt])}, got {version!r}",
                       code="E_INVALID_INPUT")

    with com_initialized():
        app = get_connected_app()
        # Saving must not change the drawing first, so no units preset here --
        # only a pending command is cancelled (it would block the save).
        doc = cad_engine.get_active_document(app, for_write=False)
        cad_engine.clear_pending_command(doc)
        before = get_drawing_identity(doc)

        if path is None:
            if not before.saved:
                raise CadError("This drawing has never been saved; pass path to choose a file.",
                               code="E_INVALID_INPUT")
            if read(doc, "ReadOnly", False):
                raise CadError("This drawing is open read-only; pass a new path to save a copy.",
                               code="E_INVALID_INPUT")
            _retry_com(lambda: doc.Save())
            target = before.path
        else:
            resolved = output_path(path, suffixes=(f".{fmt}",), overwrite=True)
            same_file = before.saved and str(resolved).lower() == before.path.lower()
            if resolved.exists() and not same_file and not overwrite:
                raise CadError(f"{resolved} already exists; pass overwrite=true to replace it",
                               code="E_OUTPUT_EXISTS", details={"path": str(resolved)})
            try:
                _retry_com(lambda: doc.SaveAs(str(resolved), SAVE_AS_TYPES[fmt][version]))
            except pywintypes.com_error as exc:
                raise RuntimeError(f"AutoCAD could not save to {resolved}: {exc}") from exc
            target = str(resolved)

        after = get_drawing_identity(doc)
        pin_moved = None
        if session.pinned_document() == before.identity and after.identity != before.identity:
            # SaveAs re-points the same document at a new file; keep it pinned.
            session.pin_document(after.identity)
            pin_moved = {"from": before.identity, "to": after.identity}

        if not os.path.isfile(target) or os.path.getsize(target) == 0:
            raise VerificationError(f"Save reported success but {target} is missing or empty.")
        clean = bool(read(doc, "Saved", True))
        return {
            "status": "ok",
            "format": fmt,
            "version": version,
            "file": file_evidence(target),
            "identity_before": before.identity,
            "drawing_identity": after.identity,
            "pin_moved": pin_moved,
            "unsaved_changes": not clean,
            "saved": True,
            "verified": clean,
            "verification": "file_on_disk_and_document_saved_flag",
            "message": f"Saved {after.name} to {target}.",
        }


def close_drawing(identity: str | None = None, discard_changes: bool = False) -> dict:
    with com_initialized():
        app = get_connected_app()
        if identity is None:
            if _retry_com(lambda: app.Documents.Count) == 0:
                raise CadError("No drawing is open.", code="E_NO_ACTIVE_DOCUMENT")
            doc = _retry_com(lambda: app.ActiveDocument)
        else:
            doc = _find(app, identity)
        record = _record(doc, _active_name(app))
        if record["unsaved_changes"] and not discard_changes:
            raise CadError(
                f"{record['name']} has unsaved changes; save it first or pass discard_changes=true.",
                code="E_UNSAVED_CHANGES",
                details={"identity": record["identity"]},
            )
        try:
            _retry_com(lambda: doc.Close(False))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"AutoCAD could not close {record['name']}: {exc}") from exc

        still_open = [get_drawing_identity(d).identity for d in _documents(app)]
        unpinned = False
        if session.pinned_document() == record["identity"]:
            session.unpin_document()
            unpinned = True
        return {
            "status": "ok",
            "closed": record,
            "discarded_changes": record["unsaved_changes"],
            "unpinned": unpinned,
            "open_drawings": still_open,
            "verified": record["identity"] not in still_open,
            "verification": "identity_no_longer_listed",
            "message": f"Closed {record['name']}" + (" without saving its changes." if record["unsaved_changes"] else "."),
        }


def activate_drawing(identity: str, pin: bool = False) -> dict:
    previous_pin = _refuse_switch_while_pinned(identity, pin)
    with com_initialized():
        app = get_connected_app()
        doc = _find(app, identity)
        _retry_com(lambda: doc.Activate())
        active = get_drawing_identity(_retry_com(lambda: app.ActiveDocument))
        if pin:
            session.pin_document(active.identity)
        return {
            "status": "ok",
            "drawing_identity": active.identity,
            "pinned": bool(pin),
            "previous_pin": previous_pin,
            "verified": active.identity == identity,
            "verification": "active_document_identity",
            "message": f"Active drawing is now {active.name}.",
        }


def set_drawing_units(preset: str) -> dict:
    key = (preset or "").strip().lower()
    if key not in units.UNIT_PRESETS:
        raise CadError(f"preset must be one of {sorted(units.UNIT_PRESETS)}, got {preset!r}",
                       code="E_INVALID_INPUT")
    with com_initialized():
        app = get_connected_app()
        doc = cad_engine.get_active_document(app, for_write=False)
        changed, failed = cad_engine._apply_variables(doc, units.preset_variables(key))
        session.set_units_override(key)
        insunits = cad_engine.read_insunits(doc)
        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "preset": key,
            "changed": changed,
            "failed": failed,
            "insunits": insunits,
            "insunits_name": units.describe(insunits) if insunits is not None else None,
            "session_preset": key,
            "verified": not failed,
            "verification": "variables_read_back_before_write",
            "drawing_identity": identity.identity,
            "message": (
                f"Applied units preset {key!r}" + (f" ({len(changed)} variable(s) changed)" if changed else " (already set)")
                + "; drawing tools now keep this preset for the rest of the session."
            ),
        }
