"""Pure civil/survey maths: stationing, ground sampling, grid volumes and
pipe clearance (domain/civil.py). No CAD engine involved."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from domain import civil
from utils.geometry import ValidationError

L_SHAPE = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]


# ======= station and offset =======


def test_station_offset_on_first_segment_uses_right_positive_sign():
    right = civil.station_offset(L_SHAPE, (50, -10))
    assert right["station"] == pytest.approx(50)
    assert right["offset"] == pytest.approx(10)   # below +X travel = right = positive
    left = civil.station_offset(L_SHAPE, (50, 10))
    assert left["offset"] == pytest.approx(-10)


def test_station_offset_on_second_segment_and_at_start_station():
    result = civil.station_offset(L_SHAPE, (110, 50))
    # second leg runs +Y; right of +Y is +X, so offset is positive
    assert result["station"] == pytest.approx(150)
    assert result["offset"] == pytest.approx(10)
    assert result["segment_index"] == 1
    shifted = civil.station_offset(L_SHAPE, (0, 0), start_station=1000.0)
    assert shifted["station"] == pytest.approx(1000)


def test_station_offset_reports_centreline_z_and_difference():
    line = [(0.0, 0.0, 10.0), (100.0, 0.0, 12.0)]
    result = civil.station_offset(line, (50, 0, 12.5))
    assert result["closest_point"][2] == pytest.approx(11.0)
    assert result["z_difference"] == pytest.approx(1.5)
    assert result["plan_distance"] == pytest.approx(0.0, abs=1e-9)


def test_point_at_station_offset_and_tangent():
    result = civil.point_at_station(L_SHAPE, 50, offset=3)
    assert result["point"] == [50.0, -3.0, 0.0]   # right of +X travel is -Y
    assert result["tangent_angle_degrees"] == pytest.approx(0)
    corner = civil.point_at_station(L_SHAPE, 150)
    assert corner["point"] == [100.0, 50.0, 0.0]
    assert corner["tangent_angle_degrees"] == pytest.approx(90)
    assert corner["clamped"] is False


def test_point_at_station_clamps_outside_the_centreline():
    before = civil.point_at_station(L_SHAPE, -5)
    assert before["point"] == [0.0, 0.0, 0.0] and before["clamped"] is True
    after = civil.point_at_station(L_SHAPE, 500)
    assert after["point"] == [100.0, 100.0, 0.0] and after["clamped"] is True


def test_point_at_station_interpolates_z_along_a_grade():
    line = [(0.0, 0.0, 100.0), (200.0, 0.0, 110.0)]
    result = civil.point_at_station(line, 50)
    assert result["point"][2] == pytest.approx(102.5)


def test_alignment_length_plan_measure_and_closed():
    assert civil.alignment_length(L_SHAPE) == pytest.approx(200)
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert civil.alignment_length(square, closed=True) == pytest.approx(40)


def test_station_series_steps_caps_and_includes_the_end():
    series = civil.station_series(0.0, 10.0, 25.0)
    assert series["stations"] == [0.0, 10.0, 20.0, 25.0]   # end station appended
    assert series["truncated"] is False
    exact = civil.station_series(100.0, 10.0, 120.0)
    assert exact["stations"] == [100.0, 110.0, 120.0]
    capped = civil.station_series(0.0, 1.0, 100.0, max_rows=5)
    assert capped["stations"] == [0.0, 1.0, 2.0, 3.0, 4.0] and capped["truncated"] is True


# ======= ground-level sampling =======


def test_sample_elevation_exact_hit_nearest_and_idw():
    samples = [(0.0, 0.0, 10.0), (10.0, 0.0, 20.0)]
    assert civil.sample_elevation(samples, 0, 0) == pytest.approx(10)
    assert civil.sample_elevation(samples, 1, 0, method="nearest") == pytest.approx(10)
    assert civil.sample_elevation(samples, 5, 0) == pytest.approx(15)  # equal weights
    assert civil.sample_elevation([], 5, 0) is None


def test_sample_elevation_validates_method_and_neighbours():
    with pytest.raises(ValidationError, match="method"):
        civil.sample_elevation([(0, 0, 0)], 0, 0, method="kriging")
    with pytest.raises(ValidationError, match="neighbours"):
        civil.sample_elevation([(0, 0, 0)], 0, 0, neighbours=0)


def test_sample_profile_rows_carry_station_point_and_elevation():
    samples = [(0.0, 0.0, 1.0), (10.0, 0.0, 3.0)]
    rows = civil.sample_profile([(0, 0, 0), (5, 5, 0)], samples)
    assert [r["station"] for r in rows] == [0, 5]
    assert rows[0]["elevation"] == pytest.approx(1.0)
    assert rows[0]["point"] == [0, 0]


# ======= grid volumes =======


CORNER_SQUARE = [(0, 0), (4, 0), (4, 4), (0, 4)]


def test_grid_volumes_flat_fill_is_exact():
    ground = [(x, y, 0.0) for x, y in CORNER_SQUARE]
    design = [(x, y, 1.0) for x, y in CORNER_SQUARE]
    result = civil.grid_volumes(ground, design, 1.0)
    assert result["cells_total"] == 16
    assert result["fill_volume"] == pytest.approx(16.0)
    assert result["cut_volume"] == pytest.approx(0.0)
    assert result["net_volume"] == pytest.approx(16.0)
    assert result["cells_fill"] == 16


def test_grid_volumes_flat_cut_and_balance():
    ground = [(x, y, 2.0) for x, y in CORNER_SQUARE]
    design = [(x, y, 1.0) for x, y in CORNER_SQUARE]
    assert civil.grid_volumes(ground, design, 1.0)["cut_volume"] == pytest.approx(16.0)
    same = civil.grid_volumes(ground, ground, 1.0)
    assert same["cut_volume"] == 0 and same["fill_volume"] == 0
    assert same["cells_balanced"] == 16


def test_grid_volumes_reports_nodes_outside_the_sample_hull():
    # ground sampled as a triangle (0,0)-(4,0)-(0,4); the grid spans the
    # 4x4 overlap, so 10 of the 25 nodes lie outside the triangle
    ground = [(0, 0, 0.0), (4, 0, 0.0), (0, 4, 0.0)]
    design = [(0, 0, 1.0), (4, 0, 1.0), (4, 4, 1.0), (0, 4, 1.0)]
    result = civil.grid_volumes(ground, design, 1.0)
    assert result["grid"]["columns"] == 5 and result["grid"]["rows"] == 5
    outside = sum(1 for i in range(5) for j in range(5) if i + j > 4)
    assert result["extrapolated_nodes"]["existing"] == outside == 10
    assert result["extrapolated_nodes"]["design"] == 0


def test_grid_volumes_requires_overlap_and_bounded_grid():
    far = [(100, 100, 0.0), (104, 100, 0.0), (104, 104, 0.0), (100, 104, 0.0)]
    near = [(0, 0, 0.0), (4, 0, 0.0), (4, 4, 0.0), (0, 4, 0.0)]
    with pytest.raises(ValidationError, match="overlap"):
        civil.grid_volumes(near, far, 1.0)
    with pytest.raises(ValidationError, match="larger cell_size"):
        civil.grid_volumes(near, near, 0.005)


# ======= segment distance and pipe clearance =======


def test_segment_segment_distance_parallel_crossing_and_degenerate():
    parallel = civil.segment_segment_distance((0, 0, 0), (10, 0, 0), (0, 5, 0), (10, 5, 0))
    assert parallel["distance"] == pytest.approx(5)
    skew = civil.segment_segment_distance((0, 0, 0), (10, 0, 0), (5, -5, 3), (5, 5, 3))
    assert skew["distance"] == pytest.approx(3)
    degenerate = civil.segment_segment_distance((0, 0, 0), (0, 0, 0), (10, 0, 0), (10, 10, 0))
    assert degenerate["distance"] == pytest.approx(10)
    clamped = civil.segment_segment_distance((0, 0, 0), (1, 0, 0), (5, 1, 0), (6, 1, 0))
    assert clamped["distance"] == pytest.approx(math.hypot(4, 1))


def test_pipe_clearance_crossing_reports_vertical_gap_and_surface_clearance():
    result = civil.pipe_clearance([(0, 0, 0), (10, 0, 0)], [(5, -5, -3), (5, 5, -3)],
                                  first_diameter=0.5, second_diameter=0.5)
    assert result["minimum_distance"] == pytest.approx(3)
    assert result["surface_clearance"] == pytest.approx(2.5)
    assert len(result["crossings"]) == 1
    crossing = result["crossings"][0]
    assert crossing["point"] == [5.0, 0.0]
    assert crossing["vertical_gap"] == pytest.approx(-3)


def test_pipe_clearance_parallel_has_no_crossing():
    result = civil.pipe_clearance([(0, 0, 0), (10, 0, 0)], [(0, 5, 0), (10, 5, 0)])
    assert result["minimum_distance"] == pytest.approx(5)
    assert result["crossings"] == []
    assert result["surface_clearance"] is None
    with pytest.raises(ValidationError, match="both diameters or neither"):
        civil.pipe_clearance([(0, 0, 0), (10, 0, 0)], [(0, 5, 0), (10, 5, 0)], first_diameter=0.5)
