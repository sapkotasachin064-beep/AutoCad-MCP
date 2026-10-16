"""Input validation for geometry, handles, and text parameters.

Every tool in entities.py/editing.py/scanning.py validates through here before
touching AutoCAD, so COM calls never run with unchecked numbers.
"""

import math
import re

HANDLE_RE = re.compile(r"^[0-9A-Fa-f]+$")


class ValidationError(ValueError):
    """Raised for bad tool input; caught at the server boundary and returned
    as a structured error instead of propagating as a COM call."""


def _require_number(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{label} must be a number, got {type(value).__name__}")
    if not math.isfinite(value):
        raise ValidationError(f"{label} must be finite, got {value}")
    return float(value)


def validate_point(point, label: str = "point") -> tuple[float, float, float]:
    if not isinstance(point, (list, tuple)) or len(point) != 3:
        raise ValidationError(f"{label} must be a [x, y, z] triple, got {point!r}")
    x, y, z = point
    return (
        _require_number(x, f"{label}.x"),
        _require_number(y, f"{label}.y"),
        _require_number(z, f"{label}.z"),
    )

def validate_point_2d_or_3d(point, label: str = "point") -> tuple[float, float, float]:
    """Accepts [x, y] (z defaults to 0.0) or [x, y, z]."""
    if isinstance(point, (list, tuple)) and len(point) == 2:
        point = (point[0], point[1], 0.0)
    return validate_point(point, label)


def validate_points(points, label: str = "points") -> list[tuple[float, float, float]]:
    if not isinstance(points, (list, tuple)) or len(points) < 2:
        raise ValidationError(f"{label} must have at least 2 points, got {points!r}")
    return [validate_point_2d_or_3d(p, f"{label}[{i}]") for i, p in enumerate(points)]


def validate_displacement(vector, label: str = "displacement") -> tuple[float, float, float]:
    return validate_point(vector, label)


def validate_radius(radius, label: str = "radius") -> float:
    value = _require_number(radius, label)
    if value <= 0:
        raise ValidationError(f"{label} must be positive, got {value}")
    return value


def validate_positive(value, label: str) -> float:
    number = _require_number(value, label)
    if number <= 0:
        raise ValidationError(f"{label} must be positive, got {number}")
    return number


def validate_angle_degrees(angle, label: str = "angle") -> float:
    return _require_number(angle, label)


def validate_text(text, label: str = "text") -> str:
    if not isinstance(text, str):
        raise ValidationError(f"{label} must be a string, got {type(text).__name__}")
    return text


def validate_layer_name(name, label: str = "layer name") -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValidationError(f"{label} must be a non-empty string, got {name!r}")
    if any(ch in name for ch in '<>/\\":;?*|,='):
        raise ValidationError(f"{label} contains characters AutoCAD does not allow in layer names: {name!r}")
    return name


def validate_handle(handle, label: str = "handle") -> str:
    if not isinstance(handle, str) or not HANDLE_RE.match(handle):
        raise ValidationError(f"{label} must be a hex entity handle string, got {handle!r}")
    return handle


def validate_color_index(color, label: str = "color index") -> int:
    if isinstance(color, bool) or not isinstance(color, int):
        raise ValidationError(f"{label} must be an int, got {type(color).__name__}")
    if not (0 <= color <= 255):
        raise ValidationError(f"{label} must be between 0 and 255, got {color}")
    return color


def degrees_to_radians(angle_degrees: float) -> float:
    return angle_degrees * math.pi / 180.0
