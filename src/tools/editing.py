"""Query and edit existing entities over COM: drawing summary, entity listing
and handles, move / rotate / copy / scale / mirror / offset / array / delete /
properties, and highlight.

Merged from modify.py, editing.py and query.py in the minimal-architecture
refactor. Every operation reads its effect back and reports `verified` with
what was checked. delete_entities is a dry run unless dry_run=False.
"""


# ======= modify.py =======
import pywintypes

from backends.com_engine import _retry_com, com_initialized, get_active_document, get_connected_app, get_drawing_identity
from core.errors import CadError, VerificationError
from tools.common import as_list, bounding_box, dxf_type, model_space, point, read
from tools.common import get_entity as lookup_entity
from tools.drawing import get_or_create_layer
from utils import geometry, validation

from utils.validation import VALID_LINEWEIGHTS  # noqa: E402  (re-exported)
_TOLERANCE = 1e-6


_validate_handles = validation.validate_handles


def _size(box):
    return [box[1][i] - box[0][i] for i in range(2)]


def scale_entity(handle: str, base_point, factor: float) -> dict:
    handle = geometry.validate_handle(handle)
    base = geometry.validate_point_2d_or_3d(base_point, "base_point")
    factor = geometry.validate_positive(factor, "factor")
    with com_initialized():
        doc = get_active_document(get_connected_app())
        entity = lookup_entity(doc, handle)
        before = bounding_box(entity)
        try:
            _retry_com(lambda: entity.ScaleEntity(point(base), factor))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to scale entity {handle}: {exc}") from exc
        after = bounding_box(lookup_entity(doc, handle))
        verification = "handle_resolves_after_edit"
        if before and after:
            for b, a in zip(_size(before), _size(after)):
                if b > _TOLERANCE and abs(a / b - factor) > 1e-6 * max(1.0, factor):
                    raise VerificationError(
                        f"Scale could not be verified: extent {b} became {a}, expected factor {factor}.")
            verification = "extents_scaled_by_factor"
        return {
            "status": "ok", "handle": handle, "base_point": base, "factor": factor,
            "verified": True, "verification": verification,
            "drawing_identity": get_drawing_identity(doc).identity,
            "message": f"Scaled {handle} by {factor:g} about {base}.",
        }


def mirror_entity(handle: str, axis_start, axis_end, keep_original: bool = True) -> dict:
    handle = geometry.validate_handle(handle)
    p1 = geometry.validate_point_2d_or_3d(axis_start, "axis_start")
    p2 = geometry.validate_point_2d_or_3d(axis_end, "axis_end")
    if p1[:2] == p2[:2]:
        raise geometry.ValidationError("axis_start and axis_end must be different points")
    with com_initialized():
        doc = get_active_document(get_connected_app())
        space = model_space(doc)
        entity = lookup_entity(doc, handle)
        count_before = _retry_com(lambda: space.Count)
        try:
            mirrored = _retry_com(lambda: entity.Mirror(point(p1), point(p2)))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to mirror entity {handle}: {exc}") from exc
        new_handle = _retry_com(lambda: mirrored.Handle)
        if not keep_original:
            _retry_com(lambda: entity.Delete())
        expected = count_before + (1 if keep_original else 0)
        count_after = _retry_com(lambda: space.Count)
        if count_after != expected or new_handle == handle:
            raise VerificationError(
                f"Mirror could not be verified: ModelSpace count {count_before} -> {count_after} (expected {expected})."
            )
        return {
            "status": "ok", "source_handle": handle, "new_handle": new_handle,
            "original_kept": keep_original, "axis": [p1, p2],
            "verified": True, "verification": "modelspace_count_and_new_handle",
            "drawing_identity": get_drawing_identity(doc).identity,
            "message": f"Mirrored {handle} to {new_handle}" + ("" if keep_original else "; original deleted") + ".",
        }


def offset_entity(handle: str, distance: float) -> dict:
    """AutoCAD's Offset: positive/negative distance chooses the side (for a
    closed curve, positive is outward for counterclockwise geometry)."""
    handle = geometry.validate_handle(handle)
    distance = geometry.validate_number(distance, "distance")
    if distance == 0:
        raise geometry.ValidationError("distance must not be zero")
    with com_initialized():
        doc = get_active_document(get_connected_app())
        space = model_space(doc)
        entity = lookup_entity(doc, handle)
        count_before = _retry_com(lambda: space.Count)
        try:
            created = as_list(_retry_com(lambda: entity.Offset(distance)))
        except pywintypes.com_error as exc:
            raise RuntimeError(
                f"Failed to offset entity {handle} by {distance}: {exc} "
                "(only curves -- lines, arcs, circles, polylines, ellipses, splines -- can be offset)"
            ) from exc
        new_handles = [_retry_com(lambda o=o: o.Handle) for o in created]
        count_after = _retry_com(lambda: space.Count)
        if not new_handles or count_after != count_before + len(new_handles):
            raise VerificationError(
                f"Offset could not be verified: {len(new_handles)} new object(s), "
                f"ModelSpace count {count_before} -> {count_after}."
            )
        return {
            "status": "ok", "source_handle": handle, "distance": distance, "new_handles": new_handles,
            "verified": True, "verification": "modelspace_count_matches_new_objects",
            "drawing_identity": get_drawing_identity(doc).identity,
            "message": f"Offset {handle} by {distance:g}: {len(new_handles)} new object(s).",
        }


def array_rectangular(handle: str, rows: int, columns: int, row_spacing: float, column_spacing: float) -> dict:
    handle = geometry.validate_handle(handle)
    for label, value in (("rows", rows), ("columns", columns)):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1000:
            raise geometry.ValidationError(f"{label} must be an integer from 1 to 1000, got {value!r}")
    if rows * columns < 2:
        raise geometry.ValidationError("rows x columns must be at least 2")
    if rows * columns > 10000:
        raise geometry.ValidationError("rows x columns must not exceed 10000 copies per call")
    row_spacing = geometry.validate_number(row_spacing, "row_spacing")
    column_spacing = geometry.validate_number(column_spacing, "column_spacing")
    if (rows > 1 and row_spacing == 0) or (columns > 1 and column_spacing == 0):
        raise geometry.ValidationError("spacing must be non-zero in every direction that has more than one item")
    with com_initialized():
        doc = get_active_document(get_connected_app())
        space = model_space(doc)
        entity = lookup_entity(doc, handle)
        count_before = _retry_com(lambda: space.Count)
        try:
            created = as_list(_retry_com(
                lambda: entity.ArrayRectangular(rows, columns, 1, row_spacing, column_spacing, 0.0)))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to array entity {handle}: {exc}") from exc
        new_handles = [_retry_com(lambda o=o: o.Handle) for o in created]
        expected = rows * columns - 1
        count_after = _retry_com(lambda: space.Count)
        if len(new_handles) != expected or count_after != count_before + expected:
            raise VerificationError(
                f"Array could not be verified: expected {expected} copies, got {len(new_handles)}; "
                f"ModelSpace count {count_before} -> {count_after}."
            )
        return {
            "status": "ok", "source_handle": handle, "rows": rows, "columns": columns,
            "row_spacing": row_spacing, "column_spacing": column_spacing, "new_handles": new_handles,
            "verified": True, "verification": "copy_count_and_modelspace_count",
            "drawing_identity": get_drawing_identity(doc).identity,
            "message": f"Arrayed {handle} into {rows}x{columns} ({expected} new).",
        }


def delete_entities(handles, dry_run: bool = True) -> dict:
    handles = _validate_handles(handles)
    with com_initialized():
        app = get_connected_app()
        # A dry run must not change the drawing in any way (no units preset).
        doc = get_active_document(app, for_write=not dry_run)
        found, missing = [], []
        for h in handles:
            try:
                entity = lookup_entity(doc, h)
            except CadError:
                missing.append(h)
                continue
            found.append((h, entity, {"handle": h, "type": dxf_type(read(entity, "ObjectName", "?")),
                                      "layer": read(entity, "Layer")}))
        identity = get_drawing_identity(doc).identity
        plan = [row for _, _, row in found]
        if dry_run:
            return {
                "status": "ok", "dry_run": True, "would_delete": plan, "not_found": missing,
                "drawing_identity": identity,
                "message": f"Dry run: {len(plan)} entity(ies) would be deleted; call again with dry_run=false.",
            }
        space = model_space(doc)
        count_before = _retry_com(lambda: space.Count)
        deleted, failed = [], []
        for h, entity, row in found:
            try:
                _retry_com(lambda entity=entity: entity.Delete())
                deleted.append(row)
            except pywintypes.com_error as exc:
                failed.append({**row, "error": str(exc)})
        survivors = []
        for row in deleted:
            try:
                lookup_entity(doc, row["handle"])
                survivors.append(row["handle"])
            except CadError:
                pass
        count_after = _retry_com(lambda: space.Count)
        return {
            "status": "ok", "dry_run": False, "deleted": deleted, "failed": failed, "not_found": missing,
            "modelspace_count": {"before": count_before, "after": count_after},
            "verified": not survivors and not failed,
            "verification": "deleted_handles_no_longer_resolve",
            "still_resolving": survivors,
            "drawing_identity": identity,
            "message": f"Deleted {len(deleted)} entity(ies)" + (f"; {len(failed)} failed" if failed else "") + ".",
        }


def set_entity_properties(handles, layer: str | None = None, color_index: int | None = None,
                          linetype: str | None = None, lineweight: int | None = None) -> dict:
    handles = _validate_handles(handles)
    if layer is None and color_index is None and linetype is None and lineweight is None:
        raise geometry.ValidationError("give at least one of layer, color_index, linetype, lineweight")
    if layer is not None:
        layer = geometry.validate_layer_name(layer)
    if color_index is not None:
        color_index = validation.validate_color_for_entity(color_index)
    if lineweight is not None and lineweight not in VALID_LINEWEIGHTS:
        raise geometry.ValidationError(f"lineweight must be one of {sorted(VALID_LINEWEIGHTS)} (hundredths of mm; "
                                       "-1 ByLayer, -2 ByBlock, -3 Default)")
    with com_initialized():
        doc = get_active_document(get_connected_app())
        if layer is not None:
            get_or_create_layer(doc, layer)
        if linetype is not None:
            from tools.drawing import ensure_linetype

            linetype = ensure_linetype(doc, linetype)
        changed, mismatched, missing = [], [], []
        wanted = {k: v for k, v in (("Layer", layer), ("Color", color_index), ("Linetype", linetype),
                                    ("Lineweight", lineweight)) if v is not None}
        for h in handles:
            try:
                entity = lookup_entity(doc, h)
            except CadError:
                missing.append(h)
                continue
            for prop, value in wanted.items():
                _retry_com(lambda entity=entity, prop=prop, value=value: setattr(entity, prop, value))
            actual = {prop: read(entity, prop) for prop in wanted}
            if any(str(actual[p]).lower() != str(v).lower() for p, v in wanted.items()):
                mismatched.append({"handle": h, "actual": actual})
            changed.append(h)
        return {
            "status": "ok", "changed": changed, "not_found": missing, "properties": wanted,
            "mismatched": mismatched,
            "verified": not mismatched and bool(changed),
            "verification": "properties_read_back",
            "drawing_identity": get_drawing_identity(doc).identity,
            "message": f"Updated {len(changed)} entity(ies).",
        }


# ======= editing.py =======
import re


from core import db
from backends.com_engine import point_variant
from core.errors import CadStateError
from core.evidence import validate_limit
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


# ======= query.py =======
from collections import Counter

from backends import com_engine as cad_engine
from core.evidence import page, validate_offset
from domain import units

from tools.common import point3, rad_to_deg
from utils import validation

DEFAULT_MAX_ENTITIES = 20000
MAX_VERTICES = 2000


def _open_read_only():
    app = get_connected_app()
    return cad_engine.get_active_document(app, for_write=False)


def _units_info(doc) -> dict:
    code = cad_engine.read_insunits(doc)
    lunits = cad_engine._get_variable(doc, "LUNITS")
    measurement = cad_engine._get_variable(doc, "MEASUREMENT")
    return {
        "insunits": code,
        "insunits_name": units.describe(code) if code is not None else None,
        "lunits": lunits,
        "measurement": {0: "imperial", 1: "metric"}.get(measurement, measurement),
    }


def _iterate(space, max_entities: int):
    count = _retry_com(lambda: space.Count)
    for index in range(min(count, max_entities)):
        try:
            yield _retry_com(lambda index=index: space.Item(index))
        except Exception:  # an entity AutoCAD refuses to hand out is skipped, not fatal
            continue


_validate_types = validation.validate_entity_types
_validate_layers = validation.validate_layer_filter
_validate_bbox = validation.validate_bbox
_inside = validation.box_inside


def drawing_summary(max_entities: int = DEFAULT_MAX_ENTITIES, max_layers: int = 200) -> dict:
    max_entities = validate_limit(max_entities, default=DEFAULT_MAX_ENTITIES, maximum=500000, label="max_entities")
    max_layers = validate_limit(max_layers, default=200, maximum=5000, label="max_layers")
    with com_initialized():
        doc = _open_read_only()
        space = model_space(doc)
        total = _retry_com(lambda: space.Count)
        by_type, by_layer = Counter(), Counter()
        for entity in _iterate(space, max_entities):
            by_type[dxf_type(read(entity, "ObjectName", "?"))] += 1
            by_layer[read(entity, "Layer", "?")] += 1

        layers = doc.Layers
        layer_names = [read(_retry_com(lambda i=i: layers.Item(i)), "Name") for i in range(_retry_com(lambda: layers.Count))]
        blocks = doc.Blocks
        block_names = []
        for i in range(_retry_com(lambda: blocks.Count)):
            block = _retry_com(lambda i=i: blocks.Item(i))
            if not read(block, "IsLayout", False) and not read(block, "IsXRef", False):
                name = read(block, "Name", "")
                if name and not name.startswith("*"):
                    block_names.append(name)
        layouts = doc.Layouts
        layout_names = [read(_retry_com(lambda i=i: layouts.Item(i)), "Name") for i in range(_retry_com(lambda: layouts.Count))]
        extmin = cad_engine._get_variable(doc, "EXTMIN")
        extmax = cad_engine._get_variable(doc, "EXTMAX")
        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "drawing_identity": identity.identity,
            "name": identity.name,
            "saved_to_disk": identity.saved,
            "unsaved_changes": not bool(read(doc, "Saved", True)),
            "read_only": bool(read(doc, "ReadOnly", False)),
            "units": _units_info(doc),
            "extents": {"min": point3(extmin), "max": point3(extmax)} if extmin is not None else None,
            "model_space_entities": total,
            "paper_space_entities": _retry_com(lambda: doc.PaperSpace.Count),
            "scanned_entities": min(total, max_entities),
            "truncated": total > max_entities,
            "counts_by_type": dict(by_type.most_common()),
            "counts_by_layer": dict(by_layer.most_common()),
            "layer_count": len(layer_names),
            "layers": layer_names[:max_layers],
            "layers_truncated": len(layer_names) > max_layers,
            "current_layer": read(read(doc, "ActiveLayer"), "Name"),
            "blocks": sorted(block_names)[:max_layers],
            "block_count": len(block_names),
            "layouts": layout_names,
            "message": f"{total} model-space entities on {len(layer_names)} layers.",
        }


def list_entities(entity_types=None, layers=None, bbox=None, offset: int = 0, limit: int = 100,
                  include_bbox: bool = False, max_entities: int = DEFAULT_MAX_ENTITIES) -> dict:
    wanted_types = _validate_types(entity_types)
    wanted_layers = _validate_layers(layers)
    window = _validate_bbox(bbox)
    offset = validate_offset(offset)
    limit = validate_limit(limit, default=100, maximum=5000)
    max_entities = validate_limit(max_entities, default=DEFAULT_MAX_ENTITIES, maximum=500000, label="max_entities")

    with com_initialized():
        doc = _open_read_only()
        space = model_space(doc)
        total_in_space = _retry_com(lambda: space.Count)
        rows = []
        for entity in _iterate(space, max_entities):
            kind = dxf_type(read(entity, "ObjectName", "?"))
            if wanted_types is not None and kind not in wanted_types:
                continue
            layer = read(entity, "Layer", "")
            if wanted_layers is not None and layer.lower() not in wanted_layers:
                continue
            box = bounding_box(entity) if (window is not None or include_bbox) else None
            if window is not None and (box is None or not _inside(box, window)):
                continue
            row = {"handle": read(entity, "Handle"), "type": kind, "layer": layer}
            if include_bbox:
                row["bbox"] = box
            rows.append(row)
        identity = get_drawing_identity(doc)
        window_page = page(rows, offset=offset, limit=limit)
        return {
            "status": "ok",
            "drawing_identity": identity.identity,
            "entities": window_page.pop("items"),
            **window_page,
            "scanned_entities": min(total_in_space, max_entities),
            "scan_truncated": total_in_space > max_entities,
            "filters": {"entity_types": sorted(wanted_types) if wanted_types else None,
                        "layers": layers, "bbox": bbox},
            "message": f"{window_page['total']} matching entities; returned {window_page['returned']}.",
        }


def _vertices(entity, kind: str):
    coords = [float(c) for c in as_list(read(entity, "Coordinates"))]
    step = 2 if kind == "LWPOLYLINE" else 3
    points = [coords[i:i + step] for i in range(0, len(coords) - step + 1, step)]
    return points


def describe_entity(entity, *, full: bool = True) -> dict:
    """Normalised dict for one COM entity. full=False keeps only what QC,
    takeoff and comparison need (and skips per-vertex detail beyond MAX_VERTICES)."""
    object_name = read(entity, "ObjectName", "?")
    kind = dxf_type(object_name)
    info = {"handle": read(entity, "Handle"), "type": kind, "layer": read(entity, "Layer")}
    if full:
        info.update(
            object_name=object_name,
            color=read(entity, "Color"),
            linetype=read(entity, "Linetype"),
            lineweight=read(entity, "Lineweight"),
            visible=read(entity, "Visible"),
        )
    if kind == "LINE":
        start, end = point3(read(entity, "StartPoint")), point3(read(entity, "EndPoint"))
        info.update(points=[start, end], length=read(entity, "Length"))
        if full:
            info["angle_degrees"] = rad_to_deg(read(entity, "Angle", 0.0) or 0.0)
    elif kind in ("LWPOLYLINE", "POLYLINE3D", "POLYLINE"):
        points = _vertices(entity, kind)
        closed = bool(read(entity, "Closed", False))
        info.update(points=points[:MAX_VERTICES], vertex_count=len(points), closed=closed,
                    length=read(entity, "Length"))
        if len(points) > MAX_VERTICES:
            info["points_truncated"] = True
        if closed and kind == "LWPOLYLINE":
            info["area"] = read(entity, "Area")
    elif kind == "CIRCLE":
        info.update(center=point3(read(entity, "Center")), radius=read(entity, "Radius"), area=read(entity, "Area"))
    elif kind == "ARC":
        info.update(
            center=point3(read(entity, "Center")),
            radius=read(entity, "Radius"),
            start_angle_degrees=rad_to_deg(read(entity, "StartAngle", 0.0) or 0.0),
            end_angle_degrees=rad_to_deg(read(entity, "EndAngle", 0.0) or 0.0),
            length=read(entity, "ArcLength"),
        )
    elif kind in ("TEXT", "MTEXT"):
        info.update(text=read(entity, "TextString"), insertion_point=point3(read(entity, "InsertionPoint")),
                    height=read(entity, "Height"))
        if full:
            info["rotation_degrees"] = rad_to_deg(read(entity, "Rotation", 0.0) or 0.0)
            if kind == "MTEXT":
                info["width"] = read(entity, "Width")
    elif kind == "INSERT":
        info.update(block=read(entity, "EffectiveName") or read(entity, "Name"),
                    insertion_point=point3(read(entity, "InsertionPoint")))
        if full:
            info.update(
                rotation_degrees=rad_to_deg(read(entity, "Rotation", 0.0) or 0.0),
                scale=[read(entity, "XScaleFactor"), read(entity, "YScaleFactor"), read(entity, "ZScaleFactor")],
            )
            if read(entity, "HasAttributes", False):
                info["attributes"] = block_attributes(entity)
    elif kind == "HATCH":
        info.update(pattern=read(entity, "PatternName"), area=read(entity, "Area"))
    elif kind == "DIMENSION":
        info.update(measurement=read(entity, "Measurement"))
        if full:
            info["text_override"] = read(entity, "TextOverride")
    elif kind == "ELLIPSE":
        info.update(center=point3(read(entity, "Center")), major_axis=point3(read(entity, "MajorAxis")),
                    ratio=read(entity, "RadiusRatio"), area=read(entity, "Area"))
    if full or kind not in ("LINE", "LWPOLYLINE", "POLYLINE3D", "POLYLINE", "CIRCLE", "ARC"):
        info["bbox"] = bounding_box(entity)
    return info


def block_attributes(entity) -> dict:
    """{tag: value} of a block reference's attributes ({} when it has none
    or AutoCAD will not list them)."""
    try:
        attributes = as_list(_retry_com(lambda: entity.GetAttributes()))
    except (pywintypes.com_error, AttributeError):
        return {}
    return {read(a, "TagString"): read(a, "TextString") for a in attributes}


def get_entity(handle: str) -> dict:
    handle = geometry.validate_handle(handle)
    with com_initialized():
        doc = _open_read_only()
        entity = lookup_entity(doc, handle)
        identity = get_drawing_identity(doc)
        return {"status": "ok", "drawing_identity": identity.identity, "entity": describe_entity(entity)}


def list_layers() -> dict:
    with com_initialized():
        doc = _open_read_only()
        current = read(read(doc, "ActiveLayer"), "Name")
        layers = doc.Layers
        rows = []
        for i in range(_retry_com(lambda: layers.Count)):
            layer = _retry_com(lambda i=i: layers.Item(i))
            name = read(layer, "Name")
            rows.append({
                "name": name,
                "on": read(layer, "LayerOn"),
                "frozen": read(layer, "Freeze"),
                "locked": read(layer, "Lock"),
                "color_index": read(layer, "Color"),
                "linetype": read(layer, "Linetype"),
                "lineweight": read(layer, "Lineweight"),
                "plottable": read(layer, "Plottable"),
                "current": name == current,
            })
        identity = get_drawing_identity(doc)
        return {"status": "ok", "drawing_identity": identity.identity, "count": len(rows), "layers": rows,
                "current_layer": current}


def snapshot_entities(max_entities: int = DEFAULT_MAX_ENTITIES) -> dict:
    """Normalised geometry of every top-level model-space entity (bounded)."""
    max_entities = validate_limit(max_entities, default=DEFAULT_MAX_ENTITIES, maximum=500000, label="max_entities")
    with com_initialized():
        doc = _open_read_only()
        space = model_space(doc)
        total = _retry_com(lambda: space.Count)
        entities = [describe_entity(e, full=False) for e in _iterate(space, max_entities)]
        identity = get_drawing_identity(doc)
        return {
            "drawing_identity": identity.identity,
            "units": _units_info(doc),
            "entities": entities,
            "total": total,
            "truncated": total > max_entities,
        }
