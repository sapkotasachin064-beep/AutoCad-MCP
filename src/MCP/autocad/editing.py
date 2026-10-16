"""Entity editing tools: move_entity, rotate_entity, copy_entity,
highlight_entity, highlight_text_matches.

Angle convention for rotate_entity: degrees, counterclockwise-positive when
viewed from the +Z axis looking down at the XY plane, matching AutoCAD's own
Rotate() COM method and ROTATE command convention. Callers in a 3D/rotated
UCS should account for that themselves; this tool does not reinterpret the
current UCS.
"""

import re

import pywintypes

from . import geometry
from .com_utils import point_variant
from .connection import _retry_com, com_initialized, get_active_document, get_connected_app
from .entity_types import TEXT_OBJECT_NAMES
from .identity import get_drawing_identity

ORIGIN = (0.0, 0.0, 0.0)
AC_ALL_VIEWPORTS = 1


def _get_entity(doc, handle: str):
    try:
        return _retry_com(lambda: doc.HandleToObject(handle))
    except pywintypes.com_error as exc:
        raise RuntimeError(f"No entity found with handle {handle!r}: {exc}") from exc


def _regen(doc) -> None:
    try:
        _retry_com(lambda: doc.Regen(AC_ALL_VIEWPORTS))
    except pywintypes.com_error:
        pass  # Cosmetic only; a failed regen does not invalidate the edit.


def move_entity(handle: str, displacement) -> dict:
    handle = geometry.validate_handle(handle)
    disp = geometry.validate_displacement(displacement)

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app)
        entity = _get_entity(doc, handle)

        try:
            _retry_com(lambda: entity.Move(point_variant(ORIGIN), point_variant(disp)))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to move entity {handle}: {exc}") from exc

        # Read back through the handle again to confirm the entity still
        # resolves after the edit.
        _get_entity(doc, handle)

        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "handle": handle,
            "displacement": disp,
            "drawing_identity": identity.identity,
            "message": f"Moved entity {handle} by {disp}.",
        }


def rotate_entity(handle: str, base_point, angle_degrees: float) -> dict:
    handle = geometry.validate_handle(handle)
    base = geometry.validate_point_2d_or_3d(base_point, "base_point")
    angle_degrees = geometry.validate_angle_degrees(angle_degrees)

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app)
        entity = _get_entity(doc, handle)

        try:
            _retry_com(
                lambda: entity.Rotate(point_variant(base), geometry.degrees_to_radians(angle_degrees))
            )
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to rotate entity {handle}: {exc}") from exc

        _get_entity(doc, handle)

        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "handle": handle,
            "base_point": base,
            "angle_degrees": angle_degrees,
            "angle_convention": "counterclockwise-positive, viewed from +Z",
            "drawing_identity": identity.identity,
            "message": f"Rotated entity {handle} by {angle_degrees} degrees about {base}.",
        }


def copy_entity(handle: str, displacement) -> dict:
    handle = geometry.validate_handle(handle)
    disp = geometry.validate_displacement(displacement)

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app)
        entity = _get_entity(doc, handle)
        model_space = _retry_com(lambda: doc.ModelSpace)
        count_before = _retry_com(lambda: model_space.Count)

        try:
            new_entity = _retry_com(lambda: entity.Copy())
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to copy entity {handle}: {exc}") from exc

        try:
            _retry_com(lambda: new_entity.Move(point_variant(ORIGIN), point_variant(disp)))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Entity copied but failed to move the copy: {exc}") from exc

        count_after = _retry_com(lambda: model_space.Count)
        new_handle = _retry_com(lambda: new_entity.Handle)
        if count_after != count_before + 1 or new_handle == handle:
            raise RuntimeError(
                f"Copy could not be verified: ModelSpace count went {count_before} -> {count_after}, "
                f"new handle {new_handle!r} vs source {handle!r}."
            )

        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "source_handle": handle,
            "new_handle": new_handle,
            "displacement": disp,
            "drawing_identity": identity.identity,
            "message": f"Copied entity {handle} to new entity {new_handle}, offset by {disp}.",
        }


def highlight_entity(
    handle: str,
    method: str = "temporary",
    color: int = 1,
    clear: bool = False,
) -> dict:
    handle = geometry.validate_handle(handle)
    if method not in ("temporary", "persistent"):
        raise geometry.ValidationError(f"method must be 'temporary' or 'persistent', got {method!r}")
    if method == "persistent":
        color = geometry.validate_color_index(color)

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app)
        entity = _get_entity(doc, handle)

        if method == "temporary":
            want_on = not clear
            try:
                _retry_com(lambda: entity.Highlight(want_on))
            except pywintypes.com_error as exc:
                raise RuntimeError(f"Failed to set temporary highlight on {handle}: {exc}") from exc
            _regen(doc)
            identity = get_drawing_identity(doc)
            return {
                "status": "ok",
                "handle": handle,
                "method": "temporary",
                "highlighted": want_on,
                "color": _retry_com(lambda: entity.Color),
                "drawing_identity": identity.identity,
                "message": f"Entity {handle} temporary highlight set to {want_on}; original color untouched.",
            }

        original_color = _retry_com(lambda: entity.Color)
        try:
            _retry_com(lambda: setattr(entity, "Color", color))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to set persistent highlight color on {handle}: {exc}") from exc
        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "handle": handle,
            "method": "persistent",
            "original_color": original_color,
            "color": color,
            "drawing_identity": identity.identity,
            "message": f"Entity {handle} color changed from {original_color} to {color} (persistent).",
        }


def highlight_text_matches(
    pattern: str,
    use_regex: bool = False,
    method: str = "temporary",
    color: int = 1,
    clear: bool = False,
) -> dict:
    pattern = geometry.validate_text(pattern, "pattern")
    if not pattern and not use_regex:
        raise geometry.ValidationError("pattern must not be empty")
    if method not in ("temporary", "persistent"):
        raise geometry.ValidationError(f"method must be 'temporary' or 'persistent', got {method!r}")
    if method == "persistent":
        color = geometry.validate_color_index(color)
    compiled = None
    if use_regex:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise geometry.ValidationError(f"pattern is not a valid regex: {exc}") from exc

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app)
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
            except pywintypes.com_error:
                continue

            is_match = bool(compiled.search(text)) if compiled else (pattern in text)
            if not is_match:
                continue

            handle = _retry_com(lambda: entity.Handle)
            if method == "temporary":
                want_on = not clear
                _retry_com(lambda: entity.Highlight(want_on))
                matches.append({"handle": handle, "text": text, "highlighted": want_on})
            else:
                original_color = _retry_com(lambda: entity.Color)
                _retry_com(lambda: setattr(entity, "Color", color))
                matches.append({"handle": handle, "text": text, "original_color": original_color, "color": color})

        if method == "temporary":
            _regen(doc)

        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "pattern": pattern,
            "use_regex": use_regex,
            "method": method,
            "match_count": len(matches),
            "matches": matches,
            "drawing_identity": identity.identity,
            "message": f"{len(matches)} text entity(ies) matched {pattern!r}; text content was not modified.",
        }
