"""Drawing creation and geometry entity tools: create_new_drawing, draw_line,
draw_polyline, draw_rectangle, draw_circle, draw_text, and the V0.1.0
create_test_drawing_with_line fixture.

Every draw_* function validates its input through utils/geometry.py, creates
the entity, verifies it actually landed in ModelSpace (count + ObjectName
read-back, same pattern as the V0.1.0 test-drawing path), then applies the
optional layer without touching doc.ActiveLayer.
"""

import os
from datetime import datetime

import pywintypes

from cad_engine import _retry_com, com_initialized, flat_variant, get_active_document, get_connected_app, get_drawing_identity, point_variant
from core import session
from core.errors import CadStateError, VerificationError
from core.paths import input_path
from tools.layers import apply_layer_to_entity
from utils import geometry
from utils.constants import get_output_dir


def _model_space(doc):
    return _retry_com(lambda: doc.ModelSpace)


def _verify_added(model_space, count_before: int, expected_object_name: str, entity):
    count_after = _retry_com(lambda: model_space.Count)
    object_name = _retry_com(lambda: entity.ObjectName)
    if count_after != count_before + 1 or object_name != expected_object_name:
        raise VerificationError(
            f"Entity creation could not be verified: expected ModelSpace count "
            f"{count_before + 1} and ObjectName {expected_object_name!r}, got "
            f"count {count_after} and ObjectName {object_name!r}."
        )


def _validate_template(template):
    """A bare file name ("acad.dwt") is passed through for AutoCAD to find on
    its own template path; anything with a folder must be an existing .dwt."""
    if template is None:
        return None
    if not isinstance(template, str) or not template.strip():
        raise geometry.ValidationError(f"template must be a non-empty string, got {template!r}")
    template = template.strip()
    if os.path.basename(template) == template:
        if not template.lower().endswith(".dwt"):
            raise geometry.ValidationError(f"template must be a .dwt file, got {template!r}")
        return template
    return str(input_path(template, suffixes=(".dwt",)))


def create_new_drawing(template: str | None = None, pin: bool = False) -> dict:
    """Documents.Add(), never touching disk. While a document pin is set the
    new drawing would become active and break the pinned job, so this refuses
    unless pin=True, which moves the pin to the new drawing."""
    template = _validate_template(template)
    previous_pin = session.pinned_document()
    if previous_pin is not None and not pin:
        raise CadStateError(
            f"This session is pinned to {previous_pin!r}; creating a drawing would switch the active "
            "drawing away from it. Pass pin=true to move the pin to the new drawing, or unpin first.",
            code="E_DOCUMENT_PINNED",
            details={"pinned_document": previous_pin},
        )

    with com_initialized():
        app = get_connected_app()
        try:
            doc = _retry_com(lambda: app.Documents.Add(template)) if template else _retry_com(
                lambda: app.Documents.Add()
            )
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create new drawing: {exc}") from exc

        active = _retry_com(lambda: app.ActiveDocument)
        if active.Name != doc.Name:
            raise RuntimeError(
                f"New drawing {doc.Name!r} was created but is not the active document "
                f"(active is {active.Name!r}); refusing to proceed against the wrong drawing."
            )

        identity = get_drawing_identity(doc)
        if pin:
            session.pin_document(identity.identity)
        return {
            "status": "ok",
            "drawing_name": doc.Name,
            "drawing_identity": identity.identity,
            "saved": identity.saved,
            "pinned": bool(pin),
            "previous_pin": previous_pin,
            "verified": True,
            "verification": "new_document_is_active",
            "message": f"Created new drawing {doc.Name!r}." + (" Pinned." if pin else ""),
        }


def draw_line(start_point, end_point, layer: str | None = None) -> dict:
    start = geometry.validate_point_2d_or_3d(start_point, "start_point")
    end = geometry.validate_point_2d_or_3d(end_point, "end_point")
    if layer is not None:
        layer = geometry.validate_layer_name(layer)

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app)
        model_space = _model_space(doc)
        count_before = _retry_com(lambda: model_space.Count)

        try:
            line = _retry_com(lambda: model_space.AddLine(point_variant(start), point_variant(end)))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create line: {exc}") from exc

        _verify_added(model_space, count_before, "AcDbLine", line)
        if layer is not None:
            apply_layer_to_entity(doc, line, layer)

        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "handle": line.Handle,
            "start_point": start,
            "end_point": end,
            "layer": _retry_com(lambda: line.Layer),
            "verified": True,
            "verification": "modelspace_count_plus_one_and_object_name",
            "drawing_identity": identity.identity,
            "message": f"Created line {line.Handle} from {start} to {end}.",
        }


def draw_polyline(points, closed: bool = False, layer: str | None = None) -> dict:
    validated_points = geometry.validate_points(points, "points")
    if layer is not None:
        layer = geometry.validate_layer_name(layer)

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app)
        model_space = _model_space(doc)
        count_before = _retry_com(lambda: model_space.Count)

        flat = [coord for point in validated_points for coord in point]
        try:
            pline = _retry_com(lambda: model_space.Add3DPoly(flat_variant(flat)))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create polyline: {exc}") from exc

        if closed:
            try:
                _retry_com(lambda: setattr(pline, "Closed", True))
            except pywintypes.com_error as exc:
                raise RuntimeError(f"Polyline created but failed to close it: {exc}") from exc

        _verify_added(model_space, count_before, "AcDb3dPolyline", pline)
        if layer is not None:
            apply_layer_to_entity(doc, pline, layer)

        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "handle": pline.Handle,
            "points": validated_points,
            "closed": closed,
            "layer": _retry_com(lambda: pline.Layer),
            "verified": True,
            "verification": "modelspace_count_plus_one_and_object_name",
            "drawing_identity": identity.identity,
            "message": f"Created polyline {pline.Handle} with {len(validated_points)} points.",
        }


def draw_rectangle(
    corner1=None,
    corner2=None,
    base_point=None,
    width: float | None = None,
    height: float | None = None,
    layer: str | None = None,
) -> dict:
    by_corners = corner1 is not None and corner2 is not None
    by_size = base_point is not None and width is not None and height is not None
    if by_corners == by_size:
        raise geometry.ValidationError(
            "draw_rectangle needs exactly one of: (corner1 and corner2), or "
            "(base_point and width and height)"
        )

    if by_corners:
        c1 = geometry.validate_point_2d_or_3d(corner1, "corner1")
        c2 = geometry.validate_point_2d_or_3d(corner2, "corner2")
        if c1[2] != c2[2]:
            raise geometry.ValidationError(
                f"corner1 and corner2 must lie in the same z-plane, got z={c1[2]} and z={c2[2]}"
            )
        x1, y1, z = c1
        x2, y2, _ = c2
    else:
        base = geometry.validate_point_2d_or_3d(base_point, "base_point")
        width = geometry.validate_positive(width, "width")
        height = geometry.validate_positive(height, "height")
        x1, y1, z = base
        x2, y2 = x1 + width, y1 + height

    rect_points = [(x1, y1, z), (x2, y1, z), (x2, y2, z), (x1, y2, z)]
    return draw_polyline(rect_points, closed=True, layer=layer)


def draw_circle(center, radius, layer: str | None = None) -> dict:
    center_point = geometry.validate_point_2d_or_3d(center, "center")
    radius = geometry.validate_radius(radius)
    if layer is not None:
        layer = geometry.validate_layer_name(layer)

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app)
        model_space = _model_space(doc)
        count_before = _retry_com(lambda: model_space.Count)

        try:
            circle = _retry_com(lambda: model_space.AddCircle(point_variant(center_point), radius))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create circle: {exc}") from exc

        _verify_added(model_space, count_before, "AcDbCircle", circle)
        if layer is not None:
            apply_layer_to_entity(doc, circle, layer)

        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "handle": circle.Handle,
            "center": center_point,
            "radius": radius,
            "layer": _retry_com(lambda: circle.Layer),
            "verified": True,
            "verification": "modelspace_count_plus_one_and_object_name",
            "drawing_identity": identity.identity,
            "message": f"Created circle {circle.Handle} at {center_point} with radius {radius}.",
        }


def draw_text(
    text: str,
    insertion_point,
    height: float,
    rotation_degrees: float = 0.0,
    layer: str | None = None,
) -> dict:
    text = geometry.validate_text(text)
    point = geometry.validate_point_2d_or_3d(insertion_point, "insertion_point")
    height = geometry.validate_positive(height, "height")
    rotation_degrees = geometry.validate_angle_degrees(rotation_degrees, "rotation_degrees")
    if layer is not None:
        layer = geometry.validate_layer_name(layer)

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app)
        model_space = _model_space(doc)
        count_before = _retry_com(lambda: model_space.Count)

        try:
            text_obj = _retry_com(lambda: model_space.AddText(text, point_variant(point), height))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create text: {exc}") from exc

        if rotation_degrees:
            try:
                _retry_com(
                    lambda: setattr(text_obj, "Rotation", geometry.degrees_to_radians(rotation_degrees))
                )
            except pywintypes.com_error as exc:
                raise RuntimeError(f"Text created but failed to set rotation: {exc}") from exc

        _verify_added(model_space, count_before, "AcDbText", text_obj)
        if layer is not None:
            apply_layer_to_entity(doc, text_obj, layer)

        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "handle": text_obj.Handle,
            "text": text,
            "insertion_point": point,
            "height": height,
            "rotation_degrees": rotation_degrees,
            "layer": _retry_com(lambda: text_obj.Layer),
            "verified": True,
            "verification": "modelspace_count_plus_one_and_object_name",
            "drawing_identity": identity.identity,
            "message": f"Created text {text_obj.Handle} at {point}.",
        }


# ======= V0.1.0 test fixture =======

_TEST_START_POINT = (0.0, 0.0, 0.0)
_TEST_END_POINT = (100.0, 100.0, 0.0)


def _unique_test_path(output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    while True:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        candidate = os.path.join(output_dir, f"mcp_test_{timestamp}.dwg")
        if not os.path.exists(candidate):
            return candidate


def create_test_drawing_with_line(output_dir: str | None = None) -> dict:
    with com_initialized():
        app = get_connected_app()
        output_dir = output_dir or get_output_dir()
        file_path = _unique_test_path(output_dir)

        try:
            doc = _retry_com(lambda: app.Documents.Add())
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create new drawing: {exc}") from exc

        active = _retry_com(lambda: app.ActiveDocument)
        if active.Name != doc.Name:
            raise RuntimeError(
                f"New drawing {doc.Name!r} was created but is not the active document "
                f"(active is {active.Name!r}); refusing to draw into the wrong drawing."
            )

        model_space = _retry_com(lambda: doc.ModelSpace)
        count_before = _retry_com(lambda: model_space.Count)

        try:
            line = _retry_com(
                lambda: model_space.AddLine(point_variant(_TEST_START_POINT), point_variant(_TEST_END_POINT))
            )
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create line entity: {exc}") from exc

        count_after = _retry_com(lambda: model_space.Count)
        if count_after != count_before + 1 or line.ObjectName != "AcDbLine":
            raise RuntimeError("Line entity was not created as expected in ModelSpace.")

        if os.path.exists(file_path):
            raise RuntimeError(f"Refusing to overwrite existing file: {file_path}")

        try:
            _retry_com(lambda: doc.SaveAs(file_path))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to save drawing to {file_path}: {exc}") from exc

        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            raise RuntimeError(f"Save reported success but file is missing or empty: {file_path}")

        return {
            "status": "ok",
            "file_path": file_path,
            "line_handle": line.Handle,
            "start_point": _TEST_START_POINT,
            "end_point": _TEST_END_POINT,
            "message": f"Drawing saved with 1 line entity at {file_path}",
        }
