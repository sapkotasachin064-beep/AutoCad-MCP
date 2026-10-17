"""Arcs, MTEXT, dimensions and hatches over COM (V0.3.0).

Angles at this boundary are degrees, counterclockwise from +X; ActiveX takes
radians, converted in tools/_common.py. Every creator verifies the entity by
ModelSpace count and ObjectName, as the V0.2.x primitives do, and reads back
the property that matters (arc angles, dimension measurement, hatch pattern
and area).

Hatch pattern type: AddHatch is called with 1, the type library's
acHatchPatternTypePreDefined (AcDbHatch::kPreDefined = 1 in ObjectARX).
Reference repositories disagree on this constant (some pass 0), so the
pattern name is read back and a mismatch fails verification instead of
being reported as success. Not yet verified against a live AutoCAD.
"""

import math

import pywintypes

from backends.com_engine import _retry_com, com_initialized, get_active_document, get_connected_app, get_drawing_identity
from core.errors import CadError, VerificationError
from tools.common import (
    as_list,
    deg_to_rad,
    dispatch_array,
    double_array,
    get_entity,
    model_space,
    point,
    rad_to_deg,
    read,
    verify_count_and_type,
)
from tools.drawing import apply_layer_to_entity
from utils import geometry

AC_HATCH_PATTERN_PREDEFINED = 1
from utils.validation import DIMENSION_KINDS  # noqa: E402,F401  (re-exported)
_ANGLE_TOLERANCE_DEG = 1e-6


def _layer(layer):
    return geometry.validate_layer_name(layer) if layer is not None else None


def _result(entity, doc, **fields) -> dict:
    return {
        "status": "ok",
        "handle": _retry_com(lambda: entity.Handle),
        "layer": _retry_com(lambda: entity.Layer),
        "verified": True,
        "verification": "modelspace_count_plus_one_and_object_name",
        "drawing_identity": get_drawing_identity(doc).identity,
        **fields,
    }


def draw_arc(center, radius, start_angle_degrees: float, end_angle_degrees: float, layer: str | None = None) -> dict:
    """Counterclockwise arc from start_angle to end_angle (degrees from +X)."""
    c = geometry.validate_point_2d_or_3d(center, "center")
    radius = geometry.validate_radius(radius)
    start = geometry.validate_angle_degrees(start_angle_degrees, "start_angle_degrees")
    end = geometry.validate_angle_degrees(end_angle_degrees, "end_angle_degrees")
    if math.isclose(start % 360.0, end % 360.0, abs_tol=_ANGLE_TOLERANCE_DEG):
        raise geometry.ValidationError("start and end angles must differ (use autocad_draw_circle for a full circle)")
    layer = _layer(layer)
    with com_initialized():
        doc = get_active_document(get_connected_app())
        space = model_space(doc)
        count_before = _retry_com(lambda: space.Count)
        try:
            arc = _retry_com(lambda: space.AddArc(point(c), radius, deg_to_rad(start), deg_to_rad(end)))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create arc: {exc}") from exc
        verify_count_and_type(space, count_before, arc, "AcDbArc")
        if layer is not None:
            apply_layer_to_entity(doc, arc, layer)
        return _result(
            arc, doc, center=c, radius=radius,
            start_angle_degrees=rad_to_deg(read(arc, "StartAngle", 0.0)),
            end_angle_degrees=rad_to_deg(read(arc, "EndAngle", 0.0)),
            arc_length=read(arc, "ArcLength"),
            message=f"Created arc r={radius:g} from {start:g} to {end:g} degrees.",
        )


def draw_mtext(text: str, insertion_point, height: float, width: float = 0.0,
               rotation_degrees: float = 0.0, layer: str | None = None) -> dict:
    """Multiline text; width 0 means no wrapping. `\\P` in text is a paragraph break."""
    text = geometry.validate_text(text)
    if not text:
        raise geometry.ValidationError("text must not be empty")
    p = geometry.validate_point_2d_or_3d(insertion_point, "insertion_point")
    height = geometry.validate_positive(height, "height")
    width = geometry.validate_number(width, "width")
    if width < 0:
        raise geometry.ValidationError("width must be >= 0")
    rotation = geometry.validate_angle_degrees(rotation_degrees, "rotation_degrees")
    layer = _layer(layer)
    with com_initialized():
        doc = get_active_document(get_connected_app())
        space = model_space(doc)
        count_before = _retry_com(lambda: space.Count)
        try:
            mtext = _retry_com(lambda: space.AddMText(point(p), width, text))
            _retry_com(lambda: setattr(mtext, "Height", height))
            if rotation:
                _retry_com(lambda: setattr(mtext, "Rotation", deg_to_rad(rotation)))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create MTEXT: {exc}") from exc
        verify_count_and_type(space, count_before, mtext, "AcDbMText")
        if layer is not None:
            apply_layer_to_entity(doc, mtext, layer)
        return _result(mtext, doc, text=text, insertion_point=p, height=read(mtext, "Height"), width=width,
                       rotation_degrees=rotation, message="Created MTEXT.")


def add_dimension(kind: str, first_point, second_point, dimension_line_point,
                  rotation_degrees: float = 0.0, text_override: str | None = None,
                  layer: str | None = None) -> dict:
    """kind="aligned": measured along the two points. kind="linear": measured
    along rotation_degrees (0 = horizontal, 90 = vertical). The dimension
    line passes through dimension_line_point. Uses the drawing's current
    dimension style."""
    if kind not in DIMENSION_KINDS:
        raise geometry.ValidationError(f"kind must be one of {list(DIMENSION_KINDS)}, got {kind!r}")
    p1 = geometry.validate_point_2d_or_3d(first_point, "first_point")
    p2 = geometry.validate_point_2d_or_3d(second_point, "second_point")
    loc = geometry.validate_point_2d_or_3d(dimension_line_point, "dimension_line_point")
    if p1[:2] == p2[:2]:
        raise geometry.ValidationError("first_point and second_point must differ")
    rotation = geometry.validate_angle_degrees(rotation_degrees, "rotation_degrees")
    if text_override is not None:
        text_override = geometry.validate_text(text_override, "text_override")
    layer = _layer(layer)
    with com_initialized():
        doc = get_active_document(get_connected_app())
        space = model_space(doc)
        count_before = _retry_com(lambda: space.Count)
        try:
            if kind == "aligned":
                dim = _retry_com(lambda: space.AddDimAligned(point(p1), point(p2), point(loc)))
                expected = "AcDbAlignedDimension"
            else:
                dim = _retry_com(lambda: space.AddDimRotated(point(p1), point(p2), point(loc), deg_to_rad(rotation)))
                expected = "AcDbRotatedDimension"
            if text_override is not None:
                _retry_com(lambda: setattr(dim, "TextOverride", text_override))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create {kind} dimension: {exc}") from exc
        verify_count_and_type(space, count_before, dim, expected)
        if layer is not None:
            apply_layer_to_entity(doc, dim, layer)
        measurement = read(dim, "Measurement")
        if kind == "aligned":
            expected_length = math.dist(p1[:2], p2[:2])
        else:
            a = math.radians(rotation)
            expected_length = abs((p2[0] - p1[0]) * math.cos(a) + (p2[1] - p1[1]) * math.sin(a))
        if measurement is not None and not math.isclose(measurement, expected_length, rel_tol=1e-6, abs_tol=1e-9):
            raise VerificationError(
                f"Dimension measures {measurement}, expected {expected_length} from the given points.")
        return _result(dim, doc, kind=kind, measurement=measurement, expected_measurement=expected_length,
                       text_override=text_override,
                       verification="modelspace_count_object_name_and_measurement",
                       message=f"Created {kind} dimension measuring {measurement}.")


def add_hatch(boundary_handles=None, boundary_points=None, pattern: str = "ANSI31", scale: float = 1.0,
              angle_degrees: float = 0.0, layer: str | None = None, keep_boundary: bool = True) -> dict:
    """Hatch one closed boundary: either boundary_handles (closed curves
    already in the drawing, forming one outer loop) or boundary_points (a
    polygon; a closed lightweight polyline is created for it and kept unless
    keep_boundary=False). pattern is a predefined acad(iso).pat name such as
    ANSI31, SOLID, AR-CONC."""
    if (boundary_handles is None) == (boundary_points is None):
        raise geometry.ValidationError("give exactly one of boundary_handles or boundary_points")
    if boundary_points is not None:
        points = geometry.validate_points(boundary_points, "boundary_points")
        if len(points) < 3:
            raise geometry.ValidationError("boundary_points needs at least 3 points")
    else:
        if not isinstance(boundary_handles, list) or not boundary_handles:
            raise geometry.ValidationError("boundary_handles must be a non-empty list")
        boundary_handles = [geometry.validate_handle(h) for h in boundary_handles]
    if not isinstance(pattern, str) or not pattern.strip() or any(c in pattern for c in ' \t\n;"'):
        raise geometry.ValidationError(f"pattern must be a pattern name like ANSI31, got {pattern!r}")
    pattern = pattern.strip().upper()
    scale = geometry.validate_positive(scale, "scale")
    angle = geometry.validate_angle_degrees(angle_degrees, "angle_degrees")
    layer = _layer(layer)

    with com_initialized():
        doc = get_active_document(get_connected_app())
        space = model_space(doc)
        created_boundary = None
        if boundary_points is not None:
            flat = [c for p in points for c in p[:2]]
            try:
                created_boundary = _retry_com(lambda: space.AddLightWeightPolyline(double_array(flat)))
                _retry_com(lambda: setattr(created_boundary, "Closed", True))
            except pywintypes.com_error as exc:
                raise RuntimeError(f"Failed to create the hatch boundary: {exc}") from exc
            loop = [created_boundary]
        else:
            loop = [get_entity(doc, h) for h in boundary_handles]
        count_before = _retry_com(lambda: space.Count)
        try:
            hatch = _retry_com(lambda: space.AddHatch(AC_HATCH_PATTERN_PREDEFINED, pattern, False))
            _retry_com(lambda: setattr(hatch, "PatternScale", scale))
            _retry_com(lambda: setattr(hatch, "PatternAngle", deg_to_rad(angle)))
            _retry_com(lambda: hatch.AppendOuterLoop(dispatch_array(loop)))
            _retry_com(lambda: hatch.Evaluate())
        except pywintypes.com_error as exc:
            raise RuntimeError(
                f"Failed to hatch with pattern {pattern!r}: {exc} (is the boundary closed and the pattern defined?)"
            ) from exc
        verify_count_and_type(space, count_before, hatch, "AcDbHatch")
        boundary_handle = _retry_com(lambda: created_boundary.Handle) if created_boundary is not None else None
        if created_boundary is not None and not keep_boundary:
            _retry_com(lambda: created_boundary.Delete())
            boundary_handle = None
        if layer is not None:
            apply_layer_to_entity(doc, hatch, layer)
        applied = str(read(hatch, "PatternName", "")).upper()
        area = read(hatch, "Area")
        if applied != pattern:
            raise VerificationError(
                f"Hatch created but its pattern reads back as {applied!r}, not {pattern!r}.",
                details={"handle": _retry_com(lambda: hatch.Handle), "pattern_read_back": applied},
            )
        return _result(hatch, doc, pattern=applied, scale=scale, angle_degrees=angle, area=area,
                       boundary_handle=boundary_handle,
                       boundary_handles=boundary_handles,
                       verification="modelspace_count_object_name_and_pattern_read_back",
                       message=f"Hatched with {applied}, area {area}.")
