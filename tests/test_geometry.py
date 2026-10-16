import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "MCP"))

from autocad import geometry


def test_validate_point_accepts_3_tuple():
    assert geometry.validate_point([1.0, 2.0, 3.0]) == (1.0, 2.0, 3.0)


def test_validate_point_rejects_wrong_length():
    with pytest.raises(geometry.ValidationError):
        geometry.validate_point([1.0, 2.0])


def test_validate_point_rejects_non_numeric():
    with pytest.raises(geometry.ValidationError):
        geometry.validate_point([1.0, "y", 3.0])


def test_validate_point_rejects_nan_and_inf():
    with pytest.raises(geometry.ValidationError):
        geometry.validate_point([float("nan"), 0.0, 0.0])
    with pytest.raises(geometry.ValidationError):
        geometry.validate_point([float("inf"), 0.0, 0.0])


def test_validate_point_rejects_bool_as_number():
    with pytest.raises(geometry.ValidationError):
        geometry.validate_point([True, 0.0, 0.0])


def test_validate_point_2d_or_3d_defaults_z():
    assert geometry.validate_point_2d_or_3d([1.0, 2.0]) == (1.0, 2.0, 0.0)


def test_validate_points_requires_at_least_two():
    with pytest.raises(geometry.ValidationError):
        geometry.validate_points([[0.0, 0.0]])


def test_validate_points_ok():
    result = geometry.validate_points([[0, 0], [1, 1], [2, 0]])
    assert result == [(0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (2.0, 0.0, 0.0)]


def test_validate_radius_positive_required():
    assert geometry.validate_radius(5) == 5.0
    with pytest.raises(geometry.ValidationError):
        geometry.validate_radius(0)
    with pytest.raises(geometry.ValidationError):
        geometry.validate_radius(-1)


def test_validate_positive():
    assert geometry.validate_positive(2.5, "height") == 2.5
    with pytest.raises(geometry.ValidationError):
        geometry.validate_positive(0, "height")


def test_validate_handle():
    assert geometry.validate_handle("2A3F") == "2A3F"
    with pytest.raises(geometry.ValidationError):
        geometry.validate_handle("not-a-handle")
    with pytest.raises(geometry.ValidationError):
        geometry.validate_handle("")
    with pytest.raises(geometry.ValidationError):
        geometry.validate_handle(123)


def test_validate_color_index_range():
    assert geometry.validate_color_index(1) == 1
    assert geometry.validate_color_index(255) == 255
    with pytest.raises(geometry.ValidationError):
        geometry.validate_color_index(256)
    with pytest.raises(geometry.ValidationError):
        geometry.validate_color_index(-1)
    with pytest.raises(geometry.ValidationError):
        geometry.validate_color_index(1.5)


def test_validate_layer_name():
    assert geometry.validate_layer_name("Walls") == "Walls"
    with pytest.raises(geometry.ValidationError):
        geometry.validate_layer_name("")
    with pytest.raises(geometry.ValidationError):
        geometry.validate_layer_name("bad/name")


def test_degrees_to_radians():
    import math

    assert geometry.degrees_to_radians(180) == pytest.approx(math.pi)
    assert geometry.degrees_to_radians(0) == 0.0
