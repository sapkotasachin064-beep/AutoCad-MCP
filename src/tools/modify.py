"""Entity modification over COM added in V0.3.0: scale, mirror, offset,
rectangular array, delete, and property changes. move / rotate / copy /
highlight stay in tools/editing.py.

Each operation reads its effect back (ModelSpace count, new handles,
extents or properties) and reports `verified` with what was checked.
delete_entities is a dry run unless dry_run=False.
"""

import pywintypes

from cad_engine import _retry_com, com_initialized, get_active_document, get_connected_app, get_drawing_identity
from core.errors import CadError, VerificationError
from tools._common import as_list, bounding_box, dxf_type, get_entity, model_space, point, read
from tools.layers import get_or_create_layer
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
        entity = get_entity(doc, handle)
        before = bounding_box(entity)
        try:
            _retry_com(lambda: entity.ScaleEntity(point(base), factor))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to scale entity {handle}: {exc}") from exc
        after = bounding_box(get_entity(doc, handle))
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
        entity = get_entity(doc, handle)
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
        entity = get_entity(doc, handle)
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
        entity = get_entity(doc, handle)
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
                entity = get_entity(doc, h)
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
                get_entity(doc, row["handle"])
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
            from tools.layers import ensure_linetype

            linetype = ensure_linetype(doc, linetype)
        changed, mismatched, missing = [], [], []
        wanted = {k: v for k, v in (("Layer", layer), ("Color", color_index), ("Linetype", linetype),
                                    ("Lineweight", lineweight)) if v is not None}
        for h in handles:
            try:
                entity = get_entity(doc, h)
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
