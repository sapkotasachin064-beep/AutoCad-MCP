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

import db
from cad_engine import _retry_com, com_initialized, get_active_document, get_connected_app, get_drawing_identity, point_variant
from core.errors import CadStateError
from core.evidence import validate_limit
from utils import geometry
from utils.constants import TEXT_OBJECT_NAMES, get_db_path

ORIGIN = (0.0, 0.0, 0.0)
AC_ALL_VIEWPORTS = 1
_MOVE_TOLERANCE = 1e-6


def _get_entity(doc, handle: str):
    try:
        return _retry_com(lambda: doc.HandleToObject(handle))
    except pywintypes.com_error as exc:
        raise CadStateError(
            f"No entity found with handle {handle!r}: {exc}",
            code="E_ENTITY_NOT_FOUND",
            details={"handle": handle},
        ) from exc


def _bounding_box(entity):
    """(min_point, max_point) as 3-tuples, or None if AutoCAD can't give one
    for this entity (some types have no extents)."""
    try:
        min_point, max_point = _retry_com(lambda: entity.GetBoundingBox())
        return tuple(min_point), tuple(max_point)
    except (pywintypes.com_error, TypeError, ValueError):
        return None


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
        before = _bounding_box(entity)

        try:
            _retry_com(lambda: entity.Move(point_variant(ORIGIN), point_variant(disp)))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to move entity {handle}: {exc}") from exc

        # Read back through the handle again to confirm the entity still
        # resolves after the edit, then check its extents shifted by exactly
        # the displacement (when AutoCAD can report extents for this type).
        entity = _get_entity(doc, handle)
        after = _bounding_box(entity)
        if before is not None and after is not None:
            expected = tuple(b + d for b, d in zip(before[0], disp))
            scale = max(1.0, *(abs(e) for e in expected))
            if max(abs(a - e) for a, e in zip(after[0], expected)) > _MOVE_TOLERANCE * scale:
                raise RuntimeError(
                    f"Move could not be verified: extents min went {before[0]} -> {after[0]}, "
                    f"expected {expected}."
                )
            verification = "bounding_box_shifted_by_displacement"
        else:
            verification = "handle_resolves_after_edit"

        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "handle": handle,
            "displacement": disp,
            "verified": True,
            "verification": verification,
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
            "verified": True,
            "verification": "handle_resolves_after_edit",
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
            "verified": True,
            "verification": "modelspace_count_plus_one_and_new_handle",
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
        # A temporary highlight is a display flag that is never saved to the
        # DWG, so it opens the drawing read-only (no units/keystroke side
        # effects); a persistent highlight changes Color and is a write.
        doc = get_active_document(app, for_write=(method == "persistent"))
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
                "verified": False,
                "verification": "not_verifiable_highlight_state_is_not_readable_over_com",
                "drawing_identity": identity.identity,
                "message": f"Entity {handle} temporary highlight set to {want_on}; original color untouched.",
            }

        original_color = _retry_com(lambda: entity.Color)
        try:
            _retry_com(lambda: setattr(entity, "Color", color))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to set persistent highlight color on {handle}: {exc}") from exc
        applied = _retry_com(lambda: entity.Color)
        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "handle": handle,
            "method": "persistent",
            "original_color": original_color,
            "color": color,
            "verified": applied == color,
            "verification": "color_read_back",
            "drawing_identity": identity.identity,
            "message": f"Entity {handle} color changed from {original_color} to {color} (persistent).",
        }


def query_and_highlight(
    query: str,
    params: list | None = None,
    method: str = "temporary",
    color: int = 1,
    clear: bool = False,
) -> dict:
    """Run a read-only query (same rules as autocad_execute_query) whose
    result set includes a 'handle' column, then highlight every matching
    entity. Stale handles (entity deleted since the last scan) are reported
    in not_found rather than aborting the batch."""
    if method not in ("temporary", "persistent"):
        raise geometry.ValidationError(f"method must be 'temporary' or 'persistent', got {method!r}")
    if method == "persistent":
        color = geometry.validate_color_index(color)

    result = db.execute_readonly_query(get_db_path(), query, params=params)
    if "handle" not in result.columns:
        raise geometry.ValidationError(
            f"query must select a 'handle' column to highlight; got columns {result.columns}"
        )

    handles = []
    seen = set()
    for row in result.rows:
        handle = row["handle"]
        if handle is None or handle in seen:
            continue
        seen.add(handle)
        handles.append(handle)

    if not handles:
        return {
            "status": "ok",
            "method": method,
            "row_count": result.row_count,
            "highlighted_count": 0,
            "highlighted_handles": [],
            "not_found": [],
            "message": "Query returned no handles to highlight.",
        }

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app, for_write=(method == "persistent"))

        highlighted = []
        not_found = []
        for handle in handles:
            try:
                entity = _get_entity(doc, handle)
            except RuntimeError:
                not_found.append(handle)
                continue
            if method == "temporary":
                want_on = not clear
                _retry_com(lambda entity=entity, want_on=want_on: entity.Highlight(want_on))
            else:
                _retry_com(lambda entity=entity, color=color: setattr(entity, "Color", color))
            highlighted.append(handle)

        if method == "temporary":
            _regen(doc)

        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "method": method,
            "color": color if method == "persistent" else None,
            "row_count": result.row_count,
            "highlighted_count": len(highlighted),
            "highlighted_handles": highlighted,
            "not_found": not_found,
            "drawing_identity": identity.identity,
            "message": f"Highlighted {len(highlighted)} of {len(handles)} entity(ies) from query result.",
        }


def highlight_text_matches(
    pattern: str,
    use_regex: bool = False,
    method: str = "temporary",
    color: int = 1,
    clear: bool = False,
    limit: int = 500,
) -> dict:
    """Highlight every matching TEXT/MTEXT entity; the returned `matches`
    list holds at most `limit` entries (match_count is the full count)."""
    pattern = geometry.validate_text(pattern, "pattern")
    limit = validate_limit(limit, default=500, maximum=10000)
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
        doc = get_active_document(app, for_write=(method == "persistent"))
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
            "matches": matches[:limit],
            "truncated": len(matches) > limit,
            "drawing_identity": identity.identity,
            "message": f"{len(matches)} text entity(ies) matched {pattern!r}; text content was not modified.",
        }
