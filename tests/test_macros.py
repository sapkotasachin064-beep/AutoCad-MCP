"""Pure logic of the architectural drawing macros: staircase, column grid, window in a wall, furniture
stamps, and the unit-driven sizes and annotation scale they share. No CAD engine involved (RecordingTarget
only); tests/test_macros_headless.py draws the same macros into real DXF files."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from backends.targets import RecordingTarget, dxf_dimension_override, emit
from core.errors import CadError
from domain import architecture, macros, units
from utils import geometry

FT, IN, MM, M, CM = (units.unit_code(u) for u in ("ft", "in", "mm", "m", "cm"))


def _by_tag(plan):
    return {p.tag: p for p in plan.primitives}


def _flat(value):
    """Nested lists/tuples of numbers as one flat list (pytest.approx takes no nested sequences)."""
    return [c for v in value for c in _flat(v)] if isinstance(value, (list, tuple)) else [value]


def _drawn(plan, insunits=MM):
    """Every primitive of the plan goes through emit(): unique tags, count verified."""
    target = RecordingTarget(insunits=insunits)
    handles = emit(plan, target)
    assert len(handles) == len(plan.primitives) == target.count(), "duplicate primitive tags"
    return handles


# ======= units: sizes follow the unit system, annotation keeps its size on paper =======


def test_default_sizes_are_natural_round_numbers_in_each_unit_system():
    assert macros.sizes(MM)["column"] == (300.0, 300.0)
    assert macros.sizes(IN)["column"] == (9.0, 12.0)
    assert macros.sizes(MM)["stair_width"] == 900.0 and macros.sizes(IN)["stair_width"] == 36.0
    assert macros.sizes(MM)["tread_depth"] == 250.0 and macros.sizes(IN)["tread_depth"] == 10.0
    assert macros.sizes(MM)["W1"] == (1200.0, 1200.0, 900.0) and macros.sizes(IN)["W1"] == (48.0, 48.0, 36.0)


def test_default_sizes_convert_to_other_units_of_the_same_system():
    assert macros.sizes(M)["column"] == pytest.approx((0.3, 0.3))
    assert macros.sizes(CM)["column"] == pytest.approx((30.0, 30.0))
    assert macros.sizes(FT)["column"] == pytest.approx((0.75, 1.0))  # 9 x 12 in
    assert macros.sizes(FT)["stair_width"] == pytest.approx(3.0)


def test_sizes_need_a_drawing_with_real_units():
    with pytest.raises(CadError) as info:
        macros.sizes(0)  # unitless drawing
    assert info.value.code == "E_UNITS_MISMATCH"


def test_annotation_scale_prints_the_same_text_size_on_paper_in_every_unit():
    heights_mm = {code: units.annotation_scale(code)["text_height"] * units.mm_per_unit(code)
                  for code in (MM, CM, M, IN, FT)}
    assert heights_mm[MM] == pytest.approx(150.0) and heights_mm[M] == pytest.approx(150.0)
    assert heights_mm[IN] == pytest.approx(6 * 25.4) and heights_mm[FT] == pytest.approx(6 * 25.4)
    assert units.annotation_scale(MM)["system"] == "metric" and units.annotation_scale(IN)["system"] == "imperial"


def test_dimension_parts_keep_iso_proportions_to_the_text():
    sizes = units.annotation_scale(MM, 200.0)["dimension"]
    assert sizes == {"text_height": 200.0, "arrow": 200.0, "extension_beyond": 100.0, "extension_offset": 50.0,
                     "text_gap": 50.0}


def test_dimension_text_shows_decimals_that_suit_the_unit():
    assert units.dimension_decimals(MM) == 0 and units.dimension_decimals(M) == 3 and units.dimension_decimals(IN) == 2
    assert units.dimension_decimals(None) == 2


def test_length_factor_converts_caller_units_into_drawing_units():
    assert units.length_factor(None, IN) == 1.0  # caller already works in drawing units
    assert units.length_factor("ft", MM) == pytest.approx(304.8)
    assert units.length_factor("mm", IN) == pytest.approx(1 / 25.4)
    with pytest.raises(CadError):
        units.length_factor("furlong", MM)


def test_dxf_dimension_override_always_resets_ezdxfs_x100_linear_factor():
    assert dxf_dimension_override(None) == {"dimlfac": 1.0}
    sized = dxf_dimension_override(150.0, MM)
    assert sized["dimlfac"] == 1.0 and sized["dimtxt"] == 150.0 and sized["dimasz"] == 150.0
    assert sized["dimexe"] == 75.0 and sized["dimexo"] == 37.5 and sized["dimgap"] == 37.5 and sized["dimdec"] == 0
    assert dxf_dimension_override(6.0, IN)["dimdec"] == 2


# ======= staircase =======


def test_staircase_draws_treads_risers_landing_handrails_arrow_and_text():
    plan = macros.plan_staircase([0, 0], 12, MM)
    assert plan.summary(0)["counts_by_layer"] == {
        "A-FLOR-TRED": 11, "A-FLOR-RISR": 12, "A-FLOR-LAND": 1, "A-FLOR-HRAL": 2, "A-ANNO-SYMB": 3, "A-ANNO-NOTE": 1}
    tags = _by_tag(plan)
    assert tags["stair:note"].text == "UP 12R" and tags["stair:note"].height == pytest.approx(150.0)
    assert {"arrow:line", "arrow:head", "arrow:tail", "landing", "handrail:left", "handrail:right"} <= set(tags)
    _drawn(plan)


def test_staircase_flight_geometry_in_a_metric_drawing():
    stair = macros.plan_staircase([0, 0], 12, MM).meta["staircase"]
    assert stair["tread_count"] == 11 and stair["tread_depth"] == 250.0 and stair["width"] == 900.0
    assert stair["run_length"] == pytest.approx(2750.0)
    assert stair["landing_depth"] == 900.0 and stair["overall_length"] == pytest.approx(3650.0)
    # rotation 90 (default): runs towards +Y and is `width` wide to the right, i.e. towards +X
    assert stair["corners"] == [[0, 0], [0, 3650], [900, 3650], [900, 0]]
    assert stair["flight_end_point"] == pytest.approx([450.0, 2750.0])


@pytest.mark.parametrize("angle,corners", [
    (0, [[0, 0], [3650, 0], [3650, -900], [0, -900]]),
    (180, [[0, 0], [-3650, 0], [-3650, 900], [0, 900]]),
    (270, [[0, 0], [0, -3650], [-900, -3650], [-900, 0]]),
])
def test_staircase_rotation_turns_the_flight_about_start_point(angle, corners):
    stair = macros.plan_staircase([0, 0], 12, MM, rotation_degrees=angle).meta["staircase"]
    assert _flat(stair["corners"]) == pytest.approx(_flat(corners))


def test_staircase_at_any_angle_keeps_its_size():
    stair = macros.plan_staircase([100, 200], 12, MM, rotation_degrees=30).meta["staircase"]
    corners = stair["corners"]
    assert math.dist(corners[0], corners[1]) == pytest.approx(3650.0)
    assert math.dist(corners[1], corners[2]) == pytest.approx(900.0)
    assert corners[0] == pytest.approx([100.0, 200.0])
    assert stair["start_point"] == [100.0, 200.0]


def test_staircase_arrow_points_away_from_start_for_up_and_dn():
    for direction in ("UP", "DN"):
        plan = macros.plan_staircase([0, 0], 10, MM, direction=direction)
        tags = _by_tag(plan)
        tail, head = plan.meta["staircase"]["walking_line"]
        assert tail[1] < head[1] and tail[0] == pytest.approx(head[0])  # +Y, along the flight's middle
        assert [q[:2] for q in tags["arrow:line"].points] == pytest.approx([tuple(tail), tuple(head)])
        assert tags["arrow:head"].points[1][:2] == pytest.approx(tuple(head))  # arrowhead tip at the far end
        assert tags["arrow:tail"].center[:2] == pytest.approx(tuple(tail))
        assert tags["stair:note"].text == f"{direction} 10R"


def test_staircase_direction_accepts_case_and_down():
    assert macros.plan_staircase([0, 0], 5, MM, direction="dn").meta["staircase"]["direction"] == "DN"
    assert macros.plan_staircase([0, 0], 5, MM, direction="Down").meta["staircase"]["direction"] == "DN"
    with pytest.raises(CadError):
        macros.plan_staircase([0, 0], 5, MM, direction="sideways")


def test_staircase_without_landing_or_handrails_creates_neither_entities_nor_layers():
    plan = macros.plan_staircase([0, 0], 12, MM, landing_depth=0, handrails=False)
    layers = plan.summary(0)["counts_by_layer"]
    assert "A-FLOR-LAND" not in layers and "A-FLOR-HRAL" not in layers
    assert "A-FLOR-LAND" not in plan.layers and "A-FLOR-HRAL" not in plan.layers
    assert plan.meta["staircase"]["overall_length"] == plan.meta["staircase"]["run_length"]


def test_staircase_sizes_follow_the_drawing_units():
    metric = macros.plan_staircase([0, 0], 12, MM).meta["staircase"]
    imperial = macros.plan_staircase([0, 0], 12, IN).meta["staircase"]
    assert (imperial["width"], imperial["tread_depth"], imperial["run_length"]) == (36.0, 10.0, 110.0)
    assert imperial["run_length"] * 25.4 == pytest.approx(metric["run_length"] * 1.016, rel=1e-9)  # 10 in vs 250 mm
    feet = macros.plan_staircase([0, 0], 12, FT).meta["staircase"]
    assert feet["width"] == pytest.approx(3.0) and feet["tread_depth"] == pytest.approx(10 / 12)


def test_staircase_caller_lengths_are_converted_from_unit():
    # 3 ft wide, 1 ft treads, drawn in a millimetre drawing
    stair = macros.plan_staircase([0, 0], 5, MM, units.length_factor("ft", MM), width=3, tread_depth=1,
                                  landing_depth=2).meta["staircase"]
    assert stair["width"] == pytest.approx(914.4) and stair["tread_depth"] == pytest.approx(304.8)
    assert stair["run_length"] == pytest.approx(4 * 304.8) and stair["landing_depth"] == pytest.approx(609.6)


def test_staircase_text_scales_with_the_units_or_the_callers_height():
    assert _by_tag(macros.plan_staircase([0, 0], 8, MM))["stair:note"].height == pytest.approx(150.0)
    assert _by_tag(macros.plan_staircase([0, 0], 8, IN))["stair:note"].height == pytest.approx(6.0)
    assert _by_tag(macros.plan_staircase([0, 0], 8, M))["stair:note"].height == pytest.approx(0.15)
    big = macros.plan_staircase([0, 0], 8, MM, units.length_factor("m", MM), text_height=0.3)
    assert _by_tag(big)["stair:note"].height == pytest.approx(300.0)
    assert big.meta["annotation"]["text_height"] == pytest.approx(300.0)


def test_staircase_arrow_and_note_stay_clear_of_the_flight_at_any_rotation():
    for angle in (0, 45, 90, 135, 180, 270):
        plan = macros.plan_staircase([0, 0], 10, MM, rotation_degrees=angle)
        stair = plan.meta["staircase"]
        note = _by_tag(plan)["stair:note"].location
        # the note is on the far side of the first riser line: negative along the run direction
        a = math.radians(angle)
        along = note[0] * math.cos(a) + note[1] * math.sin(a)
        assert along < -0.5 * 150.0, angle
        assert stair["note"] == "UP 10R"


def test_staircase_with_two_risers_has_one_tread_and_a_usable_arrow():
    plan = macros.plan_staircase([0, 0], 2, MM)
    assert plan.meta["staircase"]["tread_count"] == 1
    head = _by_tag(plan)["arrow:head"].points
    assert all(math.isfinite(c) for p in head for c in p)
    _drawn(plan)


@pytest.mark.parametrize("risers,kwargs", [
    (1, {}), (61, {}), (3.5, {}), (True, {}), ("12", {}), (5, {"width": -1}), (5, {"tread_depth": 0}),
    (5, {"landing_depth": -1}), (5, {"handrails": "yes"}), (5, {"text_height": 0}),
    (5, {"rotation_degrees": float("nan")}),
])
def test_staircase_rejects_bad_input(risers, kwargs):
    with pytest.raises(CadError) as info:
        macros.plan_staircase([0, 0], risers, MM, **kwargs)
    assert info.value.code == "E_INVALID_INPUT"


def test_staircase_rejects_a_bad_start_point():
    for bad in ("nowhere", [1], [1, "a"], None):
        with pytest.raises(CadError):
            macros.plan_staircase(bad, 5, MM)


def test_staircase_too_narrow_for_handrails_is_refused_unless_they_are_off():
    with pytest.raises(CadError) as info:
        macros.plan_staircase([0, 0], 5, MM, width=150)
    assert "handrails" in info.value.message
    assert macros.plan_staircase([0, 0], 5, MM, width=150, handrails=False).meta["staircase"]["width"] == 150


def test_staircase_check_needs_no_units():
    checked = macros.check_staircase([1, 2, 3], 12, direction="dn")
    assert checked["start"] == (1.0, 2.0) and checked["label"] == "DN"  # elevation is ignored


# ======= wall outlines and wall intersections =======


def test_outline_centerline_recovers_the_wall_from_its_outline():
    outline = geometry.wall_outline_points((0, 0, 0), (5000, 0, 0), 230)
    wall = macros.outline_centerline(outline)
    assert wall["start"] == pytest.approx((0, 0)) and wall["end"] == pytest.approx((5000, 0))
    assert wall["thickness"] == pytest.approx(230) and wall["length"] == pytest.approx(5000)
    assert wall["angle"] == pytest.approx(0)


@pytest.mark.parametrize("start,end,angle", [((0, 0, 0), (0, 4000, 0), 90), ((1000, 1000, 0), (0, 1000, 0), 180),
                                              ((0, 0, 0), (3000, 3000, 0), 45)])
def test_outline_centerline_handles_any_direction(start, end, angle):
    wall = macros.outline_centerline(geometry.wall_outline_points(start, end, 200))
    assert wall["start"] == pytest.approx(start[:2]) and wall["end"] == pytest.approx(end[:2])
    assert wall["angle"] == pytest.approx(angle) and wall["thickness"] == pytest.approx(200)


def test_outline_centerline_reads_a_plain_rectangle_polyline():
    # autocad_draw_rectangle order: corner, corner, corner, corner (long side first or second)
    wide = macros.outline_centerline([(0, 0), (4000, 0), (4000, 200), (0, 200)])
    tall = macros.outline_centerline([(0, 0), (200, 0), (200, 4000), (0, 4000)])
    assert wide["length"] == pytest.approx(4000) and wide["thickness"] == pytest.approx(200)
    assert tall["length"] == pytest.approx(4000) and tall["thickness"] == pytest.approx(200)
    assert tall["start"] == pytest.approx((100, 0)) and tall["end"] == pytest.approx((100, 4000))
    closed = macros.outline_centerline([(0, 0), (4000, 0), (4000, 200), (0, 200), (0, 0)])
    assert closed["length"] == pytest.approx(4000)


def test_outline_centerline_refuses_what_is_not_a_straight_wall():
    assert macros.outline_centerline([(0, 0), (4000, 0), (3000, 200), (0, 200)]) is None  # trapezoid
    assert macros.outline_centerline([(0, 0), (4000, 0), (4000, 200)]) is None  # triangle
    assert macros.outline_centerline([(0, 0), (300, 0), (300, 300), (0, 300)]) is None  # square: a column, not a wall
    assert macros.outline_centerline([(0, 0), (4000, 0), (4000, 0), (0, 0)]) is None  # degenerate
    assert macros.outline_centerline([(0, 0), (4000, 300), (4000, 500), (0, 200)]) is None  # parallelogram


def _wall(start, end, thickness=230, handle=None, layer="A-WALL"):
    return {"type": "POLYLINE3D", "layer": layer, "closed": True, "handle": handle,
            "points": [list(p) for p in geometry.wall_outline_points(start + (0,), end + (0,), thickness)]}


def test_wall_segments_filters_by_layer_closed_and_rectangular():
    entities = [
        _wall((0, 0), (4000, 0), handle="1"),
        _wall((0, 0), (4000, 0), handle="2", layer="A-WALL-EXT"),
        _wall((0, 0), (4000, 0), handle="3", layer="A-DOOR"),
        {"type": "LINE", "layer": "A-WALL", "points": [[0, 0, 0], [1, 0, 0]], "handle": "4"},
        {"type": "LWPOLYLINE", "layer": "A-WALL", "closed": False, "points": [[0, 0], [1, 0]], "handle": "5"},
        {"type": "LWPOLYLINE", "layer": "a-wall-int", "closed": True, "handle": "6",
         "points": [[0, 0], [4000, 0], [3000, 200], [0, 200]]},
    ]
    walls, ignored = macros.wall_segments(entities)
    assert [w["handle"] for w in walls] == ["1", "2"] and ignored == 1
    only_ext, _ = macros.wall_segments(entities, layers=["a-wall-ext"])
    assert [w["handle"] for w in only_ext] == ["2"]


def test_wall_intersections_find_corners_t_and_x_junctions():
    walls, _ = macros.wall_segments([
        _wall((0, 0), (6000, 0), handle="S"), _wall((6000, 0), (6000, 4000), handle="E"),
        _wall((6000, 4000), (0, 4000), handle="N"), _wall((0, 4000), (0, 0), handle="W"),
        _wall((3000, 0), (3000, 4000), handle="mid", thickness=115),  # T on both long walls
    ])
    points = sorted(j["point"] for j in macros.wall_intersections(walls))
    assert _flat(points) == pytest.approx(_flat(sorted([(0, 0), (6000, 0), (6000, 4000), (0, 4000), (3000, 0),
                                                                  (3000, 4000)])))
    crossing, _ = macros.wall_segments([_wall((0, 2000), (6000, 2000), handle="h"), _wall((3000, 0), (3000, 4000), handle="v")])
    cross = macros.wall_intersections(crossing)
    assert len(cross) == 1 and cross[0]["point"] == pytest.approx((3000, 2000)) and cross[0]["walls"] == ["h", "v"]


def test_wall_intersections_accept_a_wall_drawn_up_to_the_face_of_another():
    # B is 200 thick on x = 3100, so its face is x = 3000, where A stops: they meet, at B's centreline
    walls, _ = macros.wall_segments([_wall((0, 0), (3000, 0), 200, handle="A"), _wall((3100, -1000), (3100, 1000), 200, handle="B")])
    assert [j["point"] for j in macros.wall_intersections(walls)] == pytest.approx([(3100, 0)])
    # a gap wider than half of B's thickness is a gap, not a junction
    apart, _ = macros.wall_segments([_wall((0, 0), (2800, 0), 200, handle="A"), _wall((3100, -1000), (3100, 1000), 200, handle="B")])
    assert macros.wall_intersections(apart) == []


def test_wall_intersections_of_a_large_grid_of_split_walls_are_found_exactly_once():
    # 31 x 21 lines of 4 m bays, every line split into one wall per bay: 1250 walls, 651 junctions of up to four walls
    bay, columns, rows = 4000, 30, 20
    entities = []
    for i in range(columns + 1):
        for j in range(rows):
            entities.append(_wall((i * bay, j * bay), (i * bay, (j + 1) * bay), 230, handle=f"v{i}.{j}"))
    for j in range(rows + 1):
        for i in range(columns):
            entities.append(_wall((i * bay, j * bay), ((i + 1) * bay, j * bay), 230, handle=f"h{i}.{j}"))
    walls, ignored = macros.wall_segments(entities)
    assert len(walls) == 1250 and ignored == 0
    junctions = macros.wall_intersections(walls)
    found = sorted(tuple(round(c) for c in j["point"]) for j in junctions)
    assert found == sorted((i * bay, j * bay) for i in range(columns + 1) for j in range(rows + 1))
    interior = next(j for j in junctions if tuple(round(c) for c in j["point"]) == (bay, bay))
    assert interior["walls"] == sorted([f"v1.0", f"v1.1", f"h0.1", f"h1.1"])  # the four walls meeting there


def test_wall_intersections_ignore_parallel_collinear_and_distant_walls():
    walls, _ = macros.wall_segments([
        _wall((0, 0), (2000, 0), handle="a"), _wall((2000, 0), (4000, 0), handle="b"),  # one wall in two pieces
        _wall((0, 1000), (4000, 1000), handle="c"),  # parallel
        _wall((6000, -500), (6000, 500), handle="d"),  # would cross the line of a/b far beyond its end
    ])
    assert macros.wall_intersections(walls) == []


def test_wall_intersections_of_a_generated_floor_plan_are_its_corners_and_tee_joints():
    rooms = [{"name": "Living", "x": 0, "y": 0, "width": 5, "depth": 4},
             {"name": "Kitchen", "x": 5, "y": 0, "width": 3, "depth": 4},
             {"name": "Bed", "x": 0, "y": 4, "width": 5, "depth": 3.5}]
    plan = architecture.plan_room_floor_plan(rooms, M, MM, windows="none", dimensions=False)
    entities = [{"type": "POLYLINE3D", "layer": p.layer, "closed": True, "handle": p.tag,
                 "points": [list(q) for q in p.points]} for p in plan.primitives if p.kind == "polyline"]
    walls, ignored = macros.wall_segments(entities)
    assert len(walls) == plan.meta["walls"]["exterior"] + plan.meta["walls"]["interior"] and ignored == 0
    found = sorted(j["point"] for j in macros.wall_intersections(walls))
    outline = [(0, 0), (8000, 0), (8000, 4000), (5000, 4000), (5000, 7500), (0, 7500)]
    tee = [(5000, 0), (0, 4000)]  # interior walls meeting the outside
    assert _flat(found) == pytest.approx(_flat(sorted(outline + tee)))


# ======= column grid =======


def test_column_grid_marks_run_bottom_to_top_left_to_right():
    plan = macros.plan_column_grid(MM, x_spacings=[4000, 4000], y_spacings=[3000], origin=(100, 200))
    columns = plan.meta["columns"]
    assert [c["mark"] for c in columns] == ["C1", "C2", "C3", "C4", "C5", "C6"]
    assert [c["center"] for c in columns] == [[100, 200], [4100, 200], [8100, 200], [100, 3200], [4100, 3200],
                                              [8100, 3200]]
    assert [c["grid_ref"] for c in columns] == ["A1", "A2", "A3", "B1", "B2", "B3"]
    assert plan.meta["by_source"] == {"grid": 6} and plan.meta["grid"]["row_labels"] == ["A", "B"]


def test_column_grid_columns_are_outline_plus_solid_hatch_on_the_columns_layer():
    plan = macros.plan_column_grid(MM, x_spacings=[4000], y_spacings=[3000])
    kinds = plan.summary(0)["counts_by_kind"]
    assert kinds["polyline"] == 4 and kinds["hatch"] == 4
    columns = [p for p in plan.primitives if p.tag.startswith(("column:", "column_fill:"))]
    assert {p.layer for p in columns} == {"COLUMNS"} and len(columns) == 8
    assert all(p.pattern == "SOLID" for p in columns if p.kind == "hatch")
    first = _by_tag(plan)["column:C1"]
    assert first.closed and first.polyline_kind == "2d"
    xs = [p[0] for p in first.points]
    assert max(xs) - min(xs) == pytest.approx(300) and first.points[0][:2] == pytest.approx((-150, -150))
    assert plan.layers["COLUMNS"]["color"] == 5
    _drawn(plan)


def test_column_grid_default_size_is_300_mm_square_or_9_by_12_inches():
    assert macros.plan_column_grid(MM, points=[[0, 0]]).meta["column_size"] == [300.0, 300.0]
    imperial = macros.plan_column_grid(IN, points=[[0, 0]])
    assert imperial.meta["column_size"] == [9.0, 12.0]
    first = _by_tag(imperial)["column:C1"]
    xs, ys = [p[0] for p in first.points], [p[1] for p in first.points]
    assert (max(xs) - min(xs), max(ys) - min(ys)) == pytest.approx((9.0, 12.0))
    assert macros.plan_column_grid(FT, points=[[0, 0]]).meta["column_size"] == pytest.approx([0.75, 1.0])


def test_column_grid_caller_size_and_spacings_are_converted_from_unit():
    plan = macros.plan_column_grid(MM, units.length_factor("m", MM), x_spacings=[4], y_spacings=[3],
                                   column_size=[0.4, 0.25])
    assert plan.meta["column_size"] == pytest.approx([400.0, 250.0])
    assert plan.meta["grid"]["x_lines"] == pytest.approx([0.0, 4000.0])
    inches = macros.plan_column_grid(MM, units.length_factor("in", MM), points=[[0, 0]], column_size=[9, 12])
    assert inches.meta["column_size"] == pytest.approx([228.6, 304.8])


def test_column_grid_merges_duplicate_positions_and_keeps_the_first_source():
    plan = macros.plan_column_grid(MM, x_spacings=[4000], y_spacings=[3000], points=[[0, 0], [2000, 1500]],
                                   wall_points=[(4000, 0), (9000, 9000)])
    assert plan.meta["column_count"] == 6 and plan.meta["duplicates_skipped"] == 2
    assert plan.meta["by_source"] == {"grid": 4, "custom": 1, "wall_intersection": 1}
    sources = {tuple(c["center"]): c["source"] for c in plan.meta["columns"]}
    assert sources[(0.0, 0.0)] == "grid" and sources[(2000.0, 1500.0)] == "custom"
    assert sources[(9000.0, 9000.0)] == "wall_intersection"


def test_column_grid_numbers_custom_points_in_reading_order():
    plan = macros.plan_column_grid(MM, points=[[5, 5], [0, 5], [0, 0]])
    assert [(c["mark"], c["center"]) for c in plan.meta["columns"]] == [("C1", [0, 0]), ("C2", [0, 5]), ("C3", [5, 5])]
    assert all(c["grid_ref"] is None for c in plan.meta["columns"])


def test_column_grid_labels_and_dimensions_scale_and_can_be_switched_off():
    metric = macros.plan_column_grid(MM, x_spacings=[4000, 4000], y_spacings=[3000, 3000])
    dims = [p for p in metric.primitives if p.kind == "dim_linear"]
    assert len(dims) == 2 + 1 + 2 + 1 and all(p.height == pytest.approx(150.0) for p in dims)
    labels = [p for p in metric.primitives if p.kind == "text"]
    assert len(labels) == 9 and all(p.height == pytest.approx(150.0) and p.layer == "COLUMNS-TEXT" for p in labels)
    imperial = macros.plan_column_grid(IN, x_spacings=[160], y_spacings=[120])
    assert all(p.height == pytest.approx(6.0) for p in imperial.primitives if p.kind in ("text", "dim_linear"))
    bare = macros.plan_column_grid(MM, x_spacings=[4000], y_spacings=[3000], labels=False, dimensions=False)
    assert set(bare.summary(0)["counts_by_kind"]) == {"polyline", "hatch"}
    no_dims_for_points = macros.plan_column_grid(MM, points=[[0, 0], [4000, 0]])
    assert "dim_linear" not in no_dims_for_points.summary(0)["counts_by_kind"]


def test_column_grid_dimensions_sit_clear_of_the_columns():
    plan = macros.plan_column_grid(MM, x_spacings=[4000], y_spacings=[3000], origin=(0, 0))
    bottom = _by_tag(plan)["dim:x:0"]
    assert bottom.location[1] < -150.0 - 3 * 150.0  # below the lowest column face, by several text heights
    left = _by_tag(plan)["dim:y:0"]
    assert left.location[0] < -150.0 and left.rotation == 90.0


def test_column_grid_rotation_and_custom_layer():
    plan = macros.plan_column_grid(MM, points=[[0, 0]], column_size=[300, 200], rotation_degrees=90, layer="S-COLS2")
    xs = [p[0] for p in _by_tag(plan)["column:C1"].points]
    ys = [p[1] for p in _by_tag(plan)["column:C1"].points]
    assert (max(xs) - min(xs), max(ys) - min(ys)) == pytest.approx((200, 300))
    assert {"S-COLS2", "S-COLS2-TEXT"} == set(plan.layers) and plan.meta["layer"] == "S-COLS2"


def test_column_grid_rejects_bad_input():
    for kwargs in ({}, {"x_spacings": [4000]}, {"y_spacings": [4000]}, {"points": [[1]]}, {"points": [[0, 0]], "layer": "a/b"},
                   {"points": [[0, 0]], "column_size": [300]}, {"points": [[0, 0]], "column_size": [0, 300]},
                   {"x_spacings": [], "y_spacings": [1]}, {"x_spacings": [-1], "y_spacings": [1]},
                   {"points": [[0, 0]], "labels": "yes"}, {"x_spacings": [1] * 101, "y_spacings": [1]},
                   {"x_spacings": [1] * 45, "y_spacings": [1] * 45}):
        with pytest.raises(CadError) as info:
            macros.plan_column_grid(MM, **kwargs)
        assert info.value.code == "E_INVALID_INPUT", kwargs


def test_column_grid_with_no_wall_intersections_says_so():
    with pytest.raises(CadError) as info:
        macros.plan_column_grid(MM, wall_points=[])
    assert "intersections" in info.value.message


# ======= window in a wall =======

WALL = {"start": (0.0, 0.0), "end": (5000.0, 0.0), "thickness": 230.0, "length": 5000.0, "angle": 0.0,
        "layer": "A-WALL-EXT", "handle": "AB"}


def test_window_cuts_the_opening_and_draws_sills_glass_and_tag():
    plan = macros.plan_wall_window(WALL, "W1", MM)
    tags = _by_tag(plan)
    window = plan.meta["window"]
    assert window["type"] == "W1" and window["width"] == 1200.0
    assert window["opening_start"] == pytest.approx([1900, 0]) and window["opening_end"] == pytest.approx([3100, 0])
    assert window["centre"] == pytest.approx([2500, 0])
    # wall pieces stop at the opening, on the wall's own layer, as 3D polyline outlines like every wall
    start_piece, end_piece = tags["wall_piece:start"], tags["wall_piece:end"]
    assert (start_piece.layer, start_piece.polyline_kind, start_piece.closed) == ("A-WALL-EXT", "3d", True)
    assert max(p[0] for p in start_piece.points) == pytest.approx(1900) and min(p[0] for p in end_piece.points) == pytest.approx(3100)
    assert max(p[0] for p in end_piece.points) == pytest.approx(5000)
    assert sorted(abs(p[1]) for p in start_piece.points) == pytest.approx([115] * 4)
    # sill line on each wall face, two glass-pane lines across the middle, spanning exactly the opening
    assert tags["sill:left"].points[0][1] == pytest.approx(115) and tags["sill:right"].points[0][1] == pytest.approx(-115)
    assert tags["glass:left"].points[0][1] == pytest.approx(28.75) and tags["glass:right"].points[0][1] == pytest.approx(-28.75)
    for name in ("sill:left", "sill:right", "glass:left", "glass:right"):
        assert (tags[name].points[0][0], tags[name].points[1][0]) == pytest.approx((1900, 3100))
    assert plan.summary(0)["counts_by_layer"] == {"A-WALL-EXT": 2, "A-GLAZ-SILL": 2, "A-GLAZ": 3, "A-GLAZ-IDEN": 1}
    assert tags["window:tag"].text == "W1" and tags["window:tag"].height == pytest.approx(150.0)
    assert tags["window:tag"].location == pytest.approx((2500, 115 + 225, 0))
    _drawn(plan)


@pytest.mark.parametrize("tag,width,height,sill,sashes", [("W1", 1200, 1200, 900, 2), ("W2", 1800, 1200, 900, 3),
                                                          ("W3", 600, 450, 1800, 1)])
def test_window_types_differ_in_size_sash_count_and_heights(tag, width, height, sill, sashes):
    plan = macros.plan_wall_window(WALL, tag.lower(), MM)
    window = plan.meta["window"]
    assert (window["width"], window["height"], window["sill_height"]) == pytest.approx((width, height, sill))
    assert window["head_height"] == pytest.approx(sill + height) and window["sashes"] == sashes
    assert window["size_mm"] == {"width": width, "height": height, "sill_height": sill}
    mullions = [p for p in plan.primitives if p.tag.startswith("mullion:")]
    assert len(mullions) == sashes - 1 == window["mullions"]
    xs = sorted(p.points[0][0] for p in mullions)
    assert xs == pytest.approx([2500 - width / 2 + k * width / sashes for k in range(1, sashes)])
    for p in mullions:  # a tick across the pane gap
        assert abs(p.points[0][1] - p.points[1][1]) == pytest.approx(57.5)


def test_window_sizes_follow_the_drawing_units():
    wall = {**WALL, "start": (0.0, 0.0), "end": (200.0, 0.0), "thickness": 9.0, "length": 200.0}
    window = macros.plan_wall_window(wall, "W2", IN).meta["window"]
    assert (window["width"], window["height"], window["sill_height"]) == (72.0, 48.0, 36.0)
    assert window["size_mm"] == {"width": 1828.8, "height": 1219.2, "sill_height": 914.4}
    metres = {**WALL, "end": (5.0, 0.0), "thickness": 0.23, "length": 5.0}
    assert macros.plan_wall_window(metres, "W1", M).meta["window"]["width"] == pytest.approx(1.2)


def test_window_offset_width_and_unit_conversion():
    plan = macros.plan_wall_window(WALL, "W1", MM, offset=1500, width=1000)
    window = plan.meta["window"]
    assert window["offset"] == 1500 and window["width"] == 1000
    assert window["opening_start"] == pytest.approx([1000, 0]) and window["opening_end"] == pytest.approx([2000, 0])
    feet = macros.plan_wall_window(WALL, "W1", MM, units.length_factor("ft", MM), offset=8, width=4)
    assert feet.meta["window"]["width"] == pytest.approx(1219.2) and feet.meta["window"]["offset"] == pytest.approx(2438.4)


def test_window_at_the_wall_end_leaves_no_zero_length_piece():
    plan = macros.plan_wall_window(WALL, "W1", MM, offset=600)  # opening 0 .. 1200
    assert [p["name"] for p in plan.meta["wall"]["pieces"]] == ["end"]
    assert "wall_piece:start" not in _by_tag(plan)
    _drawn(plan)


def test_window_without_trim_keeps_the_wall_and_draws_jambs():
    plan = macros.plan_wall_window(WALL, "W2", MM, trim_wall=False)
    tags = _by_tag(plan)
    assert "wall_piece:start" not in tags and plan.meta["wall"]["pieces"] == [] and plan.meta["wall"]["trimmed"] is False
    assert {"jamb:start", "jamb:end"} <= set(tags)
    assert tags["jamb:start"].points[0][0] == pytest.approx(1600) and tags["jamb:end"].points[0][0] == pytest.approx(3400)
    assert "A-WALL-EXT" not in plan.layers  # nothing is drawn on the wall layer


def test_window_tag_side_and_visibility():
    left = _by_tag(macros.plan_wall_window(WALL, "W1", MM, tag_side="left"))["window:tag"].location
    right = _by_tag(macros.plan_wall_window(WALL, "W1", MM, tag_side="right"))["window:tag"].location
    assert left[1] > 0 > right[1] and left[1] == pytest.approx(-right[1])
    assert "window:tag" not in _by_tag(macros.plan_wall_window(WALL, "W1", MM, show_tag=False))


def test_window_tag_text_scales_with_the_units_or_the_callers_height():
    inch_wall = {**WALL, "end": (200.0, 0.0), "thickness": 9.0, "length": 200.0}
    assert _by_tag(macros.plan_wall_window(inch_wall, "W1", IN))["window:tag"].height == pytest.approx(6.0)
    assert _by_tag(macros.plan_wall_window(WALL, "W1", MM))["window:tag"].height == pytest.approx(150.0)
    big = macros.plan_wall_window(WALL, "W1", MM, units.length_factor("m", MM), text_height=0.25)
    assert _by_tag(big)["window:tag"].height == pytest.approx(250.0)
    assert _by_tag(big)["window:tag"].location[1] == pytest.approx(115 + 1.5 * 250)


def test_window_in_a_wall_at_any_angle():
    wall = macros.explicit_wall([0, 0], [0, 5000], 230, MM)
    assert wall["angle"] == pytest.approx(90)
    plan = macros.plan_wall_window(wall, "W1", MM)
    assert plan.meta["window"]["centre"] == pytest.approx([0, 2500])
    tag = _by_tag(plan)["window:tag"].location
    assert tag[0] == pytest.approx(-(115 + 225)) and tag[1] == pytest.approx(2500)  # left of a wall running +Y is -X
    diagonal = macros.explicit_wall([0, 0], [3000, 4000], 230, MM)
    window = macros.plan_wall_window(diagonal, "W1", MM).meta["window"]
    assert math.dist(window["opening_start"], window["opening_end"]) == pytest.approx(1200)
    assert window["centre"] == pytest.approx([1500, 2000])


def test_window_layers_follow_the_chosen_layer_name():
    plan = macros.plan_wall_window(WALL, "W1", MM, window_layer="W-GLAZ")
    assert set(plan.layers) == {"A-WALL-EXT", "W-GLAZ", "W-GLAZ-SILL", "W-GLAZ-IDEN"}


def test_window_that_does_not_fit_is_refused_with_the_valid_range():
    with pytest.raises(CadError) as info:
        macros.plan_wall_window(WALL, "W1", MM, offset=400)  # would start at -200
    assert "past the wall" in info.value.message and "600" in info.value.message and "4400" in info.value.message
    with pytest.raises(CadError):
        macros.plan_wall_window(WALL, "W1", MM, offset=4900)
    short = {**WALL, "end": (1000.0, 0.0), "length": 1000.0}
    with pytest.raises(CadError) as info:
        macros.plan_wall_window(short, "W1", MM)
    assert "does not fit" in info.value.message


@pytest.mark.parametrize("tag,kwargs", [
    ("W9", {}), (1, {}), ("", {}), ("W1", {"tag_side": "up"}), ("W1", {"width": 0}),
    ("W1", {"offset": float("inf")}), ("W1", {"trim_wall": "yes"}), ("W1", {"show_tag": 1}),
    ("W1", {"window_layer": "a:b"}), ("W1", {"text_height": -1}),
])
def test_window_rejects_bad_input(tag, kwargs):
    with pytest.raises(CadError) as info:
        macros.plan_wall_window(WALL, tag, MM, **kwargs)
    assert info.value.code == "E_INVALID_INPUT"


def test_explicit_wall_defaults_to_the_standard_exterior_wall_of_the_units():
    assert macros.explicit_wall([0, 0], [5000, 0], None, MM)["thickness"] == 230.0
    assert macros.explicit_wall([0, 0], [200, 0], None, IN)["thickness"] == 9.0
    assert macros.explicit_wall([0, 0], [5000, 0], 0.115, MM, 1000.0)["thickness"] == pytest.approx(115.0)
    wall = macros.explicit_wall([0, 0, 7], [3000, 4000, 9], 200, MM, layer="A-WALL-INT")
    assert wall["length"] == pytest.approx(5000) and wall["layer"] == "A-WALL-INT" and wall["handle"] is None
    for bad in (([0, 0], [0, 0], 200), ([0, 0], [100, 0], 200), ([0, 0], [100, 0], -5), ("a", [1, 1], 200)):
        with pytest.raises(CadError):
            macros.explicit_wall(*bad, MM)


def test_wall_from_entity_takes_closed_rectangular_outlines_only():
    entity = _wall((0, 0), (5000, 0), handle="7F", layer="A-WALL-EXT")
    wall = macros.wall_from_entity(entity)
    assert wall["handle"] == "7F" and wall["layer"] == "A-WALL-EXT" and wall["length"] == pytest.approx(5000)
    for bad in ({"type": "LINE", "handle": "1", "points": [[0, 0, 0], [1, 1, 0]]},
                {"type": "LWPOLYLINE", "handle": "2", "closed": False, "points": [[0, 0], [1, 0], [1, 1], [0, 1]]},
                {"type": "LWPOLYLINE", "handle": "3", "closed": True, "points": [[0, 0], [4000, 0], [3000, 200], [0, 200]]},
                {"type": "CIRCLE", "handle": "4"}):
        with pytest.raises(CadError) as info:
            macros.wall_from_entity(bad)
        assert bad["handle"] in info.value.message


# ======= furniture and fixtures =======


def _footprint(plan):
    f = plan.meta["furniture"]["footprint"]
    return f["width"], f["depth"]


@pytest.mark.parametrize("kind,kwargs,metric,imperial", [
    ("bed", {}, (1500, 2000), (60, 80)),
    ("bed", {"variant": "single"}, (900, 1900), (39, 75)),
    ("bed", {"variant": "king"}, (1800, 2000), (76, 80)),
    ("dining_table", {}, (1200, 1600), (48, 64)),
    ("dining_table", {"seats": 6}, (1800, 1600), (72, 64)),
    ("sofa_set", {}, (3100, 2075), (124, 83)),
    ("wc", {}, (450, 700), (17.5, 28)),
    ("kitchen_countertop", {}, (2400, 600), (96, 24)),
    ("kitchen_countertop", {"variant": "l_left"}, (2400, 1800), (96, 72)),
    ("kitchen_countertop", {"variant": "l_right"}, (2400, 1800), (96, 72)),
])
def test_furniture_standard_sizes_in_metric_and_imperial_drawings(kind, kwargs, metric, imperial):
    assert _footprint(macros.plan_furniture(kind, [0, 0], MM, **kwargs)) == pytest.approx(metric)
    assert _footprint(macros.plan_furniture(kind, [0, 0], IN, **kwargs)) == pytest.approx(imperial)


@pytest.mark.parametrize("kind", sorted(macros.FURNITURE_TYPES))
def test_furniture_is_centred_on_position_and_every_primitive_is_on_a_furn(kind):
    plan = macros.plan_furniture(kind, [1000, 2000], MM)
    assert {p.layer for p in plan.primitives} == {"A-FURN"} and plan.layers["A-FURN"]["color"] == 30
    corners = plan.meta["furniture"]["footprint"]["corners"]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    assert ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2) == pytest.approx((1000, 2000))
    assert plan.meta["furniture"]["position"] == [1000.0, 2000.0] and plan.meta["furniture"]["layer"] == "A-FURN"
    _drawn(plan)
    if kind != "wc":  # an arc's bounding box is the whole circle; every other shape is straight-sided
        box = plan.bbox()
        assert (box[0][0], box[0][1], box[1][0], box[1][1]) == pytest.approx((min(xs), min(ys), max(xs), max(ys)))


@pytest.mark.parametrize("kind", sorted(macros.FURNITURE_TYPES))
def test_furniture_rotation_turns_the_footprint_about_position(kind):
    flat = macros.plan_furniture(kind, [0, 0], MM)
    turned = macros.plan_furniture(kind, [0, 0], MM, rotation_degrees=90)
    assert _footprint(turned) == pytest.approx(_footprint(flat))  # the footprint's own width and depth
    corners = turned.meta["furniture"]["footprint"]["corners"]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    w, d = _footprint(flat)
    assert (max(xs) - min(xs), max(ys) - min(ys)) == pytest.approx((d, w))
    assert turned.meta["furniture"]["rotation_degrees"] == 90.0
    assert len(turned.primitives) == len(flat.primitives)


def test_bed_has_headboard_pillows_and_fold_line_with_the_head_towards_plus_y():
    double = macros.plan_furniture("bed", [0, 0], MM)
    tags = _by_tag(double)
    assert {"bed:mattress", "bed:headboard", "bed:pillow:0", "bed:pillow:1", "bed:fold"} <= set(tags)
    assert max(p[1] for p in tags["bed:headboard"].points) == pytest.approx(1000)  # head edge at +depth/2
    assert [t for t in tags if t.startswith("bed:pillow")] == ["bed:pillow:0", "bed:pillow:1"]
    assert [t for t in _by_tag(macros.plan_furniture("bed", [0, 0], MM, variant="single")) if t.startswith("bed:pillow")] == ["bed:pillow:0"]
    pillow = tags["bed:pillow:0"].points
    assert max(p[0] for p in pillow) - min(p[0] for p in pillow) == pytest.approx(500)
    assert double.meta["furniture"]["variant"] == "double" and double.meta["furniture"]["pillows"] == 2


def test_bed_width_and_depth_override_the_standard():
    plan = macros.plan_furniture("bed", [0, 0], MM, units.length_factor("m", MM), width=1.2, depth=1.9)
    assert _footprint(plan) == pytest.approx((1200, 1900))
    with pytest.raises(CadError):
        macros.plan_furniture("bed", [0, 0], MM, width=200)  # too narrow for its pillows
    with pytest.raises(CadError):
        macros.plan_furniture("bed", [0, 0], MM, depth=600)  # too short for headboard and pillows


def test_dining_table_seats_chairs_on_both_long_sides():
    for seats in (2, 4, 6, 8, 12):
        plan = macros.plan_furniture("dining_table", [0, 0], MM, seats=seats)
        chairs = [t for t in _by_tag(plan) if t.startswith("dining:chair:")]
        assert len(chairs) == seats and plan.meta["furniture"]["chairs"] == seats == plan.meta["furniture"]["seats"]
        assert len([t for t in chairs if ":south:" in t]) == len([t for t in chairs if ":north:" in t]) == seats // 2
    long_table = macros.plan_furniture("dining_table", [0, 0], MM, seats=4, width=2000, depth=1000)
    assert _footprint(long_table) == pytest.approx((2000, 1000 + 2 * 350))


@pytest.mark.parametrize("kwargs", [{"seats": 3}, {"seats": 0}, {"seats": 14}, {"seats": 2.5}, {"seats": 4, "width": 600}])
def test_dining_table_rejects_impossible_seating(kwargs):
    with pytest.raises(CadError):
        macros.plan_furniture("dining_table", [0, 0], MM, **kwargs)


def test_sofa_set_has_sofa_coffee_table_and_two_armchairs_facing_in():
    plan = macros.plan_furniture("sofa_set", [0, 0], MM)
    tags = _by_tag(plan)
    assert len([t for t in tags if t.startswith("sofa:seat:")]) == 3
    assert {"sofa:frame", "sofa:back", "sofa:coffee_table", "sofa:armchair:left:frame",
            "sofa:armchair:right:frame"} <= set(tags)
    assert len(plan.primitives) == 7 + 1 + 5 + 5
    # the left chair's back is its left edge, the right chair's back its right edge: they face the table
    left, right = tags["sofa:armchair:left:back"].points, tags["sofa:armchair:right:back"].points
    centre_x = sum(p[0] for p in tags["sofa:coffee_table"].points) / 4
    assert sum(p[0] for p in left) / 4 < centre_x < sum(p[0] for p in right) / 4
    assert sum(p[0] for p in left) / 4 < min(p[0] for p in tags["sofa:armchair:left:seat"].points)
    assert sum(p[0] for p in right) / 4 > max(p[0] for p in tags["sofa:armchair:right:seat"].points)
    # the sofa's back is the edge towards +Y
    assert sum(p[1] for p in tags["sofa:back"].points) / 4 > sum(p[1] for p in tags["sofa:frame"].points) / 4
    two_seater = macros.plan_furniture("sofa_set", [0, 0], MM, seats=2)
    assert len([t for t in _by_tag(two_seater) if t.startswith("sofa:seat:")]) == 2
    assert _by_tag(two_seater)["sofa:frame"].points[1][0] - _by_tag(two_seater)["sofa:frame"].points[0][0] == pytest.approx(1500)


def test_wc_has_a_cistern_a_bowl_and_a_seat_ring_made_of_arcs():
    plan = macros.plan_furniture("wc", [0, 0], MM)
    arcs = [p for p in plan.primitives if p.kind == "arc"]
    assert [a.tag for a in arcs] == ["wc:bowl:front", "wc:seat:front"]
    assert [(a.start_angle, a.end_angle) for a in arcs] == [(180.0, 0.0), (180.0, 0.0)]  # counterclockwise, the front half
    assert arcs[0].radius == pytest.approx(180) and arcs[1].radius == pytest.approx(180 * 0.78)
    turned = [p for p in macros.plan_furniture("wc", [0, 0], MM, rotation_degrees=90).primitives if p.kind == "arc"]
    assert all(a.start_angle == pytest.approx(270.0) and a.end_angle == pytest.approx(90.0) for a in turned)
    tank = _by_tag(plan)["wc:tank"].points
    assert max(p[1] for p in tank) == pytest.approx(350)  # cistern against the back (+Y) wall
    assert macros.plan_furniture("wc", [0, 0], MM, width=400, depth=750).meta["furniture"]["footprint"]["depth"] == pytest.approx(750)
    with pytest.raises(CadError):
        macros.plan_furniture("wc", [0, 0], MM, width=600, depth=300)


def test_kitchen_countertop_has_sink_and_hob_and_l_variants_add_a_return_leg():
    straight = macros.plan_furniture("kitchen_countertop", [0, 0], MM)
    tags = _by_tag(straight)
    assert {"kitchen:counter", "kitchen:sink", "kitchen:hob", "kitchen:tap"} <= set(tags)
    assert len([t for t in tags if t.startswith("kitchen:burner:")]) == 4
    assert len([t for t in tags if t.startswith("kitchen:sink:bowl:")]) == 2
    assert len(tags["kitchen:counter"].points) == 4
    sink = [p[0] for p in tags["kitchen:sink"].points]
    hob = [p[0] for p in tags["kitchen:hob"].points]
    assert max(sink) < min(hob) and min(sink) > -1200 and max(hob) < 1200  # side by side, inside the run
    for variant in ("l_left", "l_right"):
        plan = macros.plan_furniture("kitchen_countertop", [0, 0], MM, variant=variant)
        assert len(_by_tag(plan)["kitchen:counter"].points) == 6
        assert plan.meta["furniture"]["variant"] == variant
        _drawn(plan)
    long_leg = macros.plan_furniture("kitchen_countertop", [0, 0], MM, units.length_factor("m", MM), variant="l_left", return_length=2.4)
    assert _footprint(long_leg) == pytest.approx((2400, 2400))


def _area(points):
    pairs = list(zip(points, list(points[1:]) + [points[0]]))
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in pairs)) / 2.0


@pytest.mark.parametrize("variant,side", [("l_left", -1), ("l_right", 1)])
def test_l_shaped_counter_has_the_right_outline_and_keeps_sink_and_hob_off_the_corner(variant, side):
    plan = macros.plan_furniture("kitchen_countertop", [0, 0], MM, variant=variant)
    tags = _by_tag(plan)
    outline = tags["kitchen:counter"].points
    assert _area(outline) == pytest.approx(2400 * 600 + (1800 - 600) * 600)  # run plus the return leg
    top = max(p[1] for p in outline)
    leg_end = [p for p in outline if p[1] < top - 600 - 1e-6]  # only the far end of the return leg reaches this far
    assert len(leg_end) == 2 and all(side * p[0] > 0 for p in leg_end)  # side -1: left of centre, +1: right
    corner = (-1200, -600) if side < 0 else (600, 1200)  # x range of the leg, in the footprint-centred frame
    fixtures = [p[0] for tag in ("kitchen:sink", "kitchen:hob") for p in tags[tag].points]
    assert all(not corner[0] < x < corner[1] for x in fixtures)


def test_kitchen_countertop_rejects_what_cannot_hold_a_sink_and_hob():
    for kwargs in ({"width": 1000}, {"width": 2400, "depth": 460}, {"variant": "l_left", "return_length": 500},
                   {"variant": "l_left", "width": 600}):
        with pytest.raises(CadError):
            macros.plan_furniture("kitchen_countertop", [0, 0], MM, **kwargs)


def test_furniture_label_sits_in_front_of_the_item_in_text_scaled_to_the_units():
    plan = macros.plan_furniture("bed", [0, 0], MM, label=True)
    label = _by_tag(plan)["furniture:label"]
    assert (label.text, label.layer, label.kind) == ("BED", "A-FURN-TEXT", "mtext")
    assert label.height == pytest.approx(150.0) and label.location == pytest.approx((0, -(1000 + 180), 0))
    assert plan.layers["A-FURN-TEXT"]["color"] == 7
    imperial = _by_tag(macros.plan_furniture("bed", [0, 0], IN, label=True))["furniture:label"]
    assert imperial.height == pytest.approx(6.0) and imperial.location[1] == pytest.approx(-(40 + 7.2))
    assert "furniture:label" not in _by_tag(macros.plan_furniture("bed", [0, 0], MM))
    names = {k: _by_tag(macros.plan_furniture(k, [0, 0], MM, label=True))["furniture:label"].text
             for k in macros.FURNITURE_TYPES}
    assert names == {"bed": "BED", "dining_table": "DINING TABLE", "sofa_set": "SOFA SET", "wc": "WC",
                     "kitchen_countertop": "KITCHEN"}


def test_furniture_label_turns_with_the_item_but_the_text_stays_horizontal():
    label = _by_tag(macros.plan_furniture("bed", [0, 0], MM, rotation_degrees=90, label=True))["furniture:label"]
    assert label.location[:2] == pytest.approx((1180, 0))  # the bed's front now faces +X
    assert label.rotation == 0.0


def test_furniture_custom_layer_and_type_spelling():
    plan = macros.plan_furniture("Dining Table", [0, 0], MM, layer="I-FURN")
    assert {p.layer for p in plan.primitives} == {"I-FURN"}
    assert macros.furniture_type("kitchen-countertop") == "kitchen_countertop"


def test_furniture_rejects_bad_input():
    for kind, kwargs in (("piano", {}), ("bed", {"variant": "queen"}), ("wc", {"variant": "x"}), ("bed", {"seats": 2}),
                         ("wc", {"seats": 2}), ("bed", {"return_length": 500}),
                         ("kitchen_countertop", {"return_length": 500}), ("bed", {"width": -1}),
                         ("bed", {"label": "yes"}), ("bed", {"layer": "a*b"}), ("sofa_set", {"seats": 5}),
                         (None, {})):
        with pytest.raises(CadError) as info:
            macros.plan_furniture(kind, [0, 0], MM, **kwargs)
        assert info.value.code == "E_INVALID_INPUT", (kind, kwargs)
    with pytest.raises(CadError):
        macros.plan_furniture("bed", "here", MM)


def test_every_macro_plan_has_unique_tags_and_finite_coordinates():
    plans = [macros.plan_staircase([0, 0], 12, MM), macros.plan_staircase([5, 5], 3, IN, rotation_degrees=33),
             macros.plan_column_grid(MM, x_spacings=[4000] * 3, y_spacings=[3000] * 2),
             macros.plan_wall_window(WALL, "W2", MM)] + [macros.plan_furniture(k, [1, 1], MM, label=True, rotation_degrees=37)
                                                         for k in macros.FURNITURE_TYPES]
    for plan in plans:
        _drawn(plan)
        for p in plan.primitives:
            coords = [c for pt in p.points for c in pt] + list(p.center or ()) + list(p.location or ())
            assert all(math.isfinite(c) for c in coords), p.tag
            assert all(math.isfinite(v) for v in (p.radius or 0.0, p.height or 0.0))
