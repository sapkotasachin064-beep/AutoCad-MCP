"""The architectural macros (staircase, column grid, window in a wall, furniture stamps) through the same
public tool functions an MCP client calls, on the headless backend. Every drawing is saved to a real DXF in
tmp_path and read back with ezdxf, independently of the code under test."""

import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

ezdxf = pytest.importorskip("ezdxf")

import backends  # noqa: E402
import server  # noqa: E402
from core import session  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402


@pytest.fixture
def headless(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCAD_MCP_BACKEND", "dxf")
    monkeypatch.setenv("AUTOCAD_MCP_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOCAD_MCP_DB_PATH", str(tmp_path / "scan.db"))
    monkeypatch.delenv("AUTOCAD_MCP_UNITS", raising=False)
    backends._reset_for_tests()
    session.unpin_document()
    session.set_units_override(None)
    yield tmp_path
    backends._reset_for_tests()
    session.unpin_document()
    session.set_units_override(None)


@pytest.fixture
def metric(headless):
    server.autocad_create_new_drawing(pin=True)
    server.autocad_set_drawing_units("metric_mm")
    return headless


@pytest.fixture
def imperial(headless):
    server.autocad_create_new_drawing(pin=True)  # the default preset: engineering, inches
    return headless


def _read(tmp, name="out.dxf"):
    server.autocad_save_drawing(path=str(tmp / name), overwrite=True)
    return ezdxf.readfile(str(tmp / name))


def _layers(doc):
    return Counter(e.dxf.layer for e in doc.modelspace())


def _on(doc, layer, kind=None):
    return [e for e in doc.modelspace() if e.dxf.layer == layer and (kind is None or e.dxftype() == kind)]


def _error(info):
    return json.loads(str(info.value))["error"]


def _points(entity):
    return [(round(p[0], 6), round(p[1], 6)) for p in entity.get_points("xy")]


def _dimension_text(dim):
    return [v.text if v.dxftype() == "MTEXT" else v.dxf.text for v in dim.virtual_entities()
            if v.dxftype() in ("MTEXT", "TEXT")]


# ======= staircase =======


def test_staircase_is_drawn_on_its_own_layers_and_read_back_from_the_dxf(metric):
    result = server.autocad_draw_staircase([0, 0], 12)
    assert result["status"] == "ok" and result["verified"] is True and result["generator"] == "staircase"
    assert result["state"] == {"accepted": True, "preflight_passed": True, "executed": True, "verified": True,
                               "saved": False}
    assert result["entity_count"] == 30 and result["drawing_unit"] == "mm"
    assert result["staircase"]["run_length"] == pytest.approx(2750.0) and result["annotation"]["text_height"] == 150.0

    doc = _read(metric)
    assert _layers(doc) == {"A-FLOR-TRED": 11, "A-FLOR-RISR": 12, "A-FLOR-LAND": 1, "A-FLOR-HRAL": 2,
                            "A-ANNO-SYMB": 3, "A-ANNO-NOTE": 1}
    treads = _on(doc, "A-FLOR-TRED", "LWPOLYLINE")
    assert len(treads) == 11 and all(t.closed for t in treads)
    ys = sorted({y for t in treads for _, y in _points(t)})
    assert ys == [250.0 * k for k in range(12)]  # treads 250 deep, 11 of them, from y=0 to y=2750
    xs = {x for t in treads for x, _ in _points(t)}
    assert xs == {0.0, 900.0}  # default 900 mm wide, to the right of a flight running +Y
    assert sorted(round(e.dxf.start.y, 6) for e in _on(doc, "A-FLOR-RISR", "LINE")) == [250.0 * k for k in range(12)]
    landing = _points(_on(doc, "A-FLOR-LAND", "LWPOLYLINE")[0])
    assert (min(y for _, y in landing), max(y for _, y in landing)) == (2750.0, 3650.0)
    assert len(_on(doc, "A-ANNO-SYMB", "CIRCLE")) == 1 and len(_on(doc, "A-ANNO-SYMB", "LWPOLYLINE")) == 2
    note = _on(doc, "A-ANNO-NOTE", "MTEXT")[0]
    assert note.text == "UP 12R" and note.dxf.char_height == pytest.approx(150.0)
    assert {name: doc.layers.get(name).color for name in _layers(doc)} == {
        "A-FLOR-TRED": 2, "A-FLOR-RISR": 8, "A-FLOR-LAND": 3, "A-FLOR-HRAL": 4, "A-ANNO-SYMB": 6, "A-ANNO-NOTE": 7}


def test_staircase_dn_label_rotation_and_no_landing_or_handrails(metric):
    server.autocad_draw_staircase([1000, 500], 8, direction="DN", rotation_degrees=0, landing_depth=0, handrails=False,
                                  width=1000, tread_depth=300)
    doc = _read(metric)
    assert _layers(doc) == {"A-FLOR-TRED": 7, "A-FLOR-RISR": 8, "A-ANNO-SYMB": 3, "A-ANNO-NOTE": 1}
    assert _on(doc, "A-ANNO-NOTE", "MTEXT")[0].text == "DN 8R"
    tread = _points(_on(doc, "A-FLOR-TRED", "LWPOLYLINE")[0])
    # rotation 0 runs along +X from the start point and the flight is 1000 wide to the right, i.e. towards -Y
    assert sorted(set(tread)) == [(1000.0, -500.0), (1000.0, 500.0), (1300.0, -500.0), (1300.0, 500.0)]


def test_staircase_dry_run_plans_without_drawing(metric):
    result = server.autocad_draw_staircase([0, 0], 12, dry_run=True)
    assert result["dry_run"] is True and result["state"]["executed"] is False and result["state"]["verified"] is False
    assert result["plan"]["primitive_count"] == 30 and "handles" not in result
    assert server.autocad_drawing_summary()["model_space_entities"] == 0


def test_staircase_sizes_and_text_follow_an_imperial_drawing(imperial):
    result = server.autocad_draw_staircase([0, 0], 12)
    assert result["drawing_unit"] == "in" and result["staircase"]["width"] == 36.0
    assert result["staircase"]["tread_depth"] == 10.0 and result["staircase"]["run_length"] == 110.0
    note = _on(_read(imperial), "A-ANNO-NOTE", "MTEXT")[0]
    assert note.dxf.char_height == pytest.approx(6.0)


def test_unit_argument_converts_the_callers_lengths_into_the_drawing(metric):
    server.autocad_draw_staircase([0, 0], 5, width=3, tread_depth=1, landing_depth=2, unit="ft", text_height=0.4,
                                  handrails=False)
    doc = _read(metric)
    xs = {x for t in _on(doc, "A-FLOR-TRED", "LWPOLYLINE") for x, _ in _points(t)}
    assert xs == {0.0, 914.4}
    ys = sorted({y for t in _on(doc, "A-FLOR-TRED", "LWPOLYLINE") for _, y in _points(t)})
    assert ys == pytest.approx([304.8 * k for k in range(5)])
    assert _on(doc, "A-ANNO-NOTE", "MTEXT")[0].dxf.char_height == pytest.approx(0.4 * 304.8)


def test_staircase_input_errors_are_typed_and_leave_the_drawing_alone(metric):
    for kwargs in ({"riser_count": 1}, {"riser_count": 5, "direction": "SIDEWAYS"},
                   {"riser_count": 5, "width": 150}, {"riser_count": 5, "unit": "furlong"}):
        with pytest.raises(ToolError) as info:
            server.autocad_draw_staircase([0, 0], **kwargs)
        assert _error(info)["code"] == "E_INVALID_INPUT"
    assert server.autocad_drawing_summary()["model_space_entities"] == 0


# ======= column grid =======


def test_column_grid_draws_filled_columns_on_the_columns_layer(metric):
    result = server.autocad_draw_column_grid(x_spacings=[4000, 4000], y_spacings=[3000], origin=[1000, 2000])
    assert result["verified"] is True and result["column_count"] == 6 and result["by_source"] == {"grid": 6}
    assert [c["mark"] for c in result["columns"]] == ["C1", "C2", "C3", "C4", "C5", "C6"]
    assert result["columns"][0]["center"] == [1000.0, 2000.0] and result["column_size"] == [300.0, 300.0]

    doc = _read(metric)
    assert _layers(doc) == {"COLUMNS": 12, "COLUMNS-TEXT": 6, "COLUMNS-DIM": 4}
    outlines = _on(doc, "COLUMNS", "LWPOLYLINE")
    hatches = _on(doc, "COLUMNS", "HATCH")
    assert len(outlines) == 6 and len(hatches) == 6 and all(o.closed for o in outlines)
    assert all(h.dxf.pattern_name == "SOLID" and h.dxf.solid_fill == 1 for h in hatches)
    first = _points(outlines[0])
    assert (min(x for x, _ in first), max(x for x, _ in first)) == (850.0, 1150.0)  # 300 wide around x = 1000
    assert (min(y for _, y in first), max(y for _, y in first)) == (1850.0, 2150.0)
    assert sorted(t.dxf.text for t in _on(doc, "COLUMNS-TEXT", "TEXT")) == ["C1", "C2", "C3", "C4", "C5", "C6"]
    assert all(t.dxf.height == pytest.approx(150.0) for t in _on(doc, "COLUMNS-TEXT", "TEXT"))


def test_column_grid_default_column_is_9_by_12_inches_in_an_inch_drawing(imperial):
    result = server.autocad_draw_column_grid(points=[[0, 0], [120, 0]], dimensions=False)
    assert result["column_size"] == [9.0, 12.0] and result["by_source"] == {"custom": 2}
    outline = _points(_on(_read(imperial), "COLUMNS", "LWPOLYLINE")[0])
    assert (max(x for x, _ in outline) - min(x for x, _ in outline), max(y for _, y in outline) - min(y for _, y in outline)) == (9.0, 12.0)


def test_column_size_and_spacings_in_another_unit(metric):
    result = server.autocad_draw_column_grid(x_spacings=[4, 4], y_spacings=[3], unit="m", column_size=[0.4, 0.25],
                                             dimensions=False, labels=False)
    assert result["column_size"] == pytest.approx([400.0, 250.0])
    assert result["grid"]["x_lines"] == pytest.approx([0.0, 4000.0, 8000.0]) and result["grid"]["y_lines"] == pytest.approx([0.0, 3000.0])
    outline = _points(_on(_read(metric), "COLUMNS", "LWPOLYLINE")[0])
    assert (max(x for x, _ in outline) - min(x for x, _ in outline), max(y for _, y in outline) - min(y for _, y in outline)) == pytest.approx((400.0, 250.0))
    inches = server.autocad_draw_column_grid(x_spacings=[10], y_spacings=[10], unit="in", column_size=[9, 12],
                                             origin=[50000, 0], dimensions=False, labels=False)
    assert inches["column_size"] == pytest.approx([228.6, 304.8])  # the classic 9 x 12 in column in a millimetre drawing
    assert inches["grid"]["x_lines"] == pytest.approx([50000.0, 50254.0])


def test_column_grid_dimensions_read_the_true_measurement_at_a_size_that_scales(metric):
    server.autocad_draw_column_grid(x_spacings=[4000, 4000], y_spacings=[3000, 3000])
    doc = _read(metric)
    dims = _on(doc, "COLUMNS-DIM", "DIMENSION")
    assert len(dims) == 2 + 1 + 2 + 1
    texts = sorted(_dimension_text(d)[0] for d in dims)
    assert texts == ["3000", "3000", "4000", "4000", "6000", "8000"]  # not x100, and no decimals in millimetres
    for d in dims:
        style = d.override()
        assert style.get("dimlfac") == 1.0 and style.get("dimtxt") == pytest.approx(150.0)
        assert style.get("dimasz") == pytest.approx(150.0) and style.get("dimdec") == 0


def test_column_grid_dimensions_scale_to_an_inch_drawing(imperial):
    server.autocad_draw_column_grid(x_spacings=[160], y_spacings=[120])
    dims = _on(_read(imperial), "COLUMNS-DIM", "DIMENSION")
    assert sorted(_dimension_text(d)[0] for d in dims) == ["120", "160"]
    assert all(d.override().get("dimtxt") == pytest.approx(6.0) and d.override().get("dimdec") == 2 for d in dims)


def test_the_older_dimension_tool_no_longer_prints_ezdxfs_times_100(metric):
    server.autocad_add_dimension("linear", [0, 0], [3000, 0], [0, -500])
    dim = _on(_read(metric), "0", "DIMENSION")[0]
    assert dim.override().get("dimlfac") == 1.0
    assert _dimension_text(dim) == ["3000"]  # the measurement itself (it read 300000 before), zeros trimmed by the style


def test_floor_plan_and_structural_grid_dimensions_are_sized_and_true_in_the_dxf(metric):
    rooms = [{"name": "Living", "x": 0, "y": 0, "width": 5, "depth": 4}, {"name": "Kitchen", "x": 5, "y": 0, "width": 3, "depth": 4}]
    server.autocad_generate_floor_plan(rooms=rooms, unit="m")
    server.autocad_draw_structural_grid(x_spacings=[4.5, 3.0], y_spacings=[4.0], unit="m", origin=[0, -20000])
    doc = _read(metric)
    plan_dims = _on(doc, "A-DIM", "DIMENSION")
    assert sorted(_dimension_text(d)[0] for d in plan_dims) == ["4000", "8000"]
    grid_dims = _on(doc, "S-ANNO-DIMS", "DIMENSION")
    assert sorted(_dimension_text(d)[0] for d in grid_dims) == ["3000", "4000", "4500", "7500"]
    assert all(d.override().get("dimtxt") == pytest.approx(150.0) and d.override().get("dimlfac") == 1.0 for d in plan_dims)
    assert all(d.override().get("dimtxt") == pytest.approx(350.0) and d.override().get("dimdec") == 0 for d in grid_dims)


def test_column_grid_at_wall_intersections_of_a_generated_floor_plan(metric):
    rooms = [{"name": "Living", "x": 0, "y": 0, "width": 5, "depth": 4},
             {"name": "Kitchen", "x": 5, "y": 0, "width": 3, "depth": 4},
             {"name": "Bed", "x": 0, "y": 4, "width": 5, "depth": 3.5}]
    server.autocad_generate_floor_plan(rooms=rooms, unit="m", windows="none", dimensions=False)
    dry = server.autocad_draw_column_grid(at_wall_intersections=True, dry_run=True)
    assert dry["dry_run"] is True and dry["column_count"] == 8
    assert dry["wall_scan"]["walls_found"] > 8 and dry["wall_scan"]["intersections"] == 8
    assert dry["wall_scan"]["layers"] == "A-WALL*" and dry["wall_scan"]["scan_truncated"] is False
    result = server.autocad_draw_column_grid(at_wall_intersections=True, labels=False)
    assert result["by_source"] == {"wall_intersection": 8} and result["verified"] is True
    centres = sorted(tuple(c["center"]) for c in result["columns"])
    expected = sorted([(0, 0), (8000, 0), (8000, 4000), (5000, 4000), (5000, 7500), (0, 7500), (5000, 0), (0, 4000)])
    assert centres == pytest.approx(expected)
    assert len(_on(_read(metric), "COLUMNS", "HATCH")) == 8


def test_column_grid_wall_layers_filter_and_combination_with_a_grid_and_points(metric):
    rooms = [{"name": "A", "x": 0, "y": 0, "width": 4, "depth": 3}, {"name": "B", "x": 4, "y": 0, "width": 3, "depth": 3}]
    server.autocad_generate_floor_plan(rooms=rooms, unit="m", windows="none", dimensions=False)
    exterior_only = server.autocad_draw_column_grid(at_wall_intersections=True, wall_layers=["A-WALL-EXT"], dry_run=True)
    assert exterior_only["column_count"] == 4 and exterior_only["wall_scan"]["layers"] == ["A-WALL-EXT"]
    both = server.autocad_draw_column_grid(at_wall_intersections=True, points=[[0, 0], [9999, 9999]], dry_run=True)
    # (0, 0) is also a wall corner: it is drawn once, as a custom point (custom points are listed before walls)
    assert both["column_count"] == 6 + 1 and both["duplicates_skipped"] == 1
    assert both["by_source"] == {"custom": 2, "wall_intersection": 5}


def test_column_grid_at_wall_intersections_needs_walls_and_some_source(metric):
    with pytest.raises(ToolError) as info:
        server.autocad_draw_column_grid(at_wall_intersections=True)
    assert _error(info)["code"] == "E_INVALID_INPUT" and "intersections" in _error(info)["message"]
    with pytest.raises(ToolError) as info:
        server.autocad_draw_column_grid()
    assert _error(info)["code"] == "E_INVALID_INPUT" and "no column positions" in _error(info)["message"]
    with pytest.raises(ToolError) as info:
        server.autocad_draw_column_grid(x_spacings=[4000])
    assert _error(info)["code"] == "E_INVALID_INPUT"
    assert server.autocad_drawing_summary()["model_space_entities"] == 0


def test_column_grid_custom_layer_rotation_and_dry_run(metric):
    result = server.autocad_draw_column_grid(points=[[0, 0]], layer="S-COL", rotation_degrees=45, column_size=[300, 300],
                                             labels=False)
    doc = _read(metric)
    assert _layers(doc) == {"S-COL": 2}
    xs = [x for x, _ in _points(_on(doc, "S-COL", "LWPOLYLINE")[0])]
    assert max(xs) == pytest.approx(300 * 2 ** 0.5 / 2)  # the square's corner now points along +X
    assert result["layer"] == "S-COL"


# ======= window in a wall =======


def _wall(start=(0, 0), end=(5000, 0), layer="A-WALL"):
    return server.autocad_draw_wall(list(start), list(end), thickness=230, layer=layer)


def test_window_on_an_existing_wall_plans_first_then_trims_it(metric):
    wall = _wall()
    plan = server.autocad_draw_wall_window("W1", wall_handle=wall["handle"])
    assert plan["dry_run"] is True and plan["state"]["executed"] is False  # replacing a wall defaults to a dry run
    assert plan["would_replace_wall"]["handle"] == wall["handle"] and "trimmed_wall" not in plan
    assert server.autocad_drawing_summary()["model_space_entities"] == 1  # untouched
    assert server.autocad_get_entity(wall["handle"])["entity"]["handle"] == wall["handle"]

    done = server.autocad_draw_wall_window("W1", wall_handle=wall["handle"], dry_run=False)
    assert done["verified"] is True and done["state"]["executed"] is True
    trimmed = done["trimmed_wall"]
    assert trimmed["replaced_handle"] == wall["handle"] and trimmed["deleted"] is True and len(trimmed["new_handles"]) == 2
    assert done["window"]["type"] == "W1" and done["window"]["centre"] == pytest.approx([2500.0, 0.0])
    assert done["window"]["size_mm"] == {"width": 1200.0, "height": 1200.0, "sill_height": 900.0}
    with pytest.raises(ToolError) as info:  # the original outline is gone
        server.autocad_get_entity(wall["handle"])
    assert _error(info)["code"] == "E_ENTITY_NOT_FOUND"

    doc = _read(metric)
    assert _layers(doc) == {"A-WALL": 2, "A-GLAZ": 3, "A-GLAZ-SILL": 2, "A-GLAZ-IDEN": 1}
    pieces = _on(doc, "A-WALL", "POLYLINE")  # 3D polyline outlines, like every wall the server draws
    assert sorted(e.dxf.handle for e in pieces) == sorted(trimmed["new_handles"])
    spans = sorted((min(v.dxf.location.x for v in p.vertices), max(v.dxf.location.x for v in p.vertices)) for p in pieces)
    assert spans == [(0.0, 1900.0), (3100.0, 5000.0)]
    assert all(p.is_closed for p in pieces)
    glass = sorted(round(e.dxf.start.y, 6) for e in _on(doc, "A-GLAZ", "LINE") if e.dxf.start.x == pytest.approx(1900.0))
    assert glass == [-28.75, 28.75]
    sills = _on(doc, "A-GLAZ-SILL", "LINE")
    assert sorted(round(e.dxf.start.y, 6) for e in sills) == [-115.0, 115.0]
    assert all((e.dxf.start.x, e.dxf.end.x) == (1900.0, 3100.0) for e in sills)
    tag = _on(doc, "A-GLAZ-IDEN", "MTEXT")[0]
    assert tag.text == "W1" and tag.dxf.char_height == pytest.approx(150.0)


def test_wall_pieces_are_walls_to_the_takeoff_and_the_window_can_be_chained(metric):
    wall = _wall()
    first = server.autocad_draw_wall_window("W1", wall_handle=wall["handle"], offset=1000, dry_run=False)
    end_piece = first["trimmed_wall"]["new_handles"][-1]  # the piece towards the far end: x = 1600 .. 5000
    takeoff = server.autocad_quantity_takeoff()
    assert takeoff["layers"]["A-WALL"]["walls"]["count"] == 2
    assert takeoff["layers"]["A-WALL"]["walls"]["length"] == pytest.approx(5000 - 1200)
    # a second window, measured from the start of the remaining piece (which starts at x = 1600)
    second = server.autocad_draw_wall_window("W3", wall_handle=end_piece, offset=2000, dry_run=False)
    assert second["window"]["centre"] == pytest.approx([3600.0, 0.0]) and second["window"]["width"] == 600.0
    takeoff = server.autocad_quantity_takeoff()
    assert takeoff["layers"]["A-WALL"]["walls"]["count"] == 3
    assert takeoff["layers"]["A-WALL"]["walls"]["length"] == pytest.approx(5000 - 1200 - 600)
    assert _layers(_read(metric))["A-GLAZ-IDEN"] == 2


def test_window_in_a_new_wall_draws_the_wall_with_the_opening_and_deletes_nothing(metric):
    result = server.autocad_draw_wall_window("W2", wall_start=[0, 0], wall_end=[0, 6000], thickness=200,
                                             offset=2000, tag_side="right", wall_layer="A-WALL-EXT")
    assert result["dry_run"] is False and result["verified"] is True  # nothing is replaced, so it draws at once
    assert result["trimmed_wall"]["deleted"] is False and result["trimmed_wall"]["replaced_handle"] is None
    assert result["wall"]["thickness"] == 200.0 and result["wall"]["length"] == 6000.0 and result["wall"]["layer"] == "A-WALL-EXT"
    doc = _read(metric)
    assert _layers(doc)["A-WALL-EXT"] == 2
    spans = sorted((min(v.dxf.location.y for v in p.vertices), max(v.dxf.location.y for v in p.vertices))
                   for p in _on(doc, "A-WALL-EXT", "POLYLINE"))
    assert spans == [(0.0, 1100.0), (2900.0, 6000.0)]  # W2 is 1800 wide, centred 2000 along the wall
    tag = _on(doc, "A-GLAZ-IDEN", "MTEXT")[0]
    assert tag.text == "W2" and tag.dxf.insert.x > 0  # the right-hand side of a wall running +Y is +X


def test_window_with_a_new_wall_takes_the_thickness_and_width_from_the_drawing_units(imperial):
    result = server.autocad_draw_wall_window("W2", wall_start=[0, 0], wall_end=[240, 0])
    assert result["wall"]["thickness"] == 9.0 and result["window"]["width"] == 72.0
    assert result["window"]["size_mm"]["width"] == pytest.approx(1828.8)
    doc = _read(imperial)
    tag = _on(doc, "A-GLAZ-IDEN", "MTEXT")[0]
    assert tag.dxf.char_height == pytest.approx(6.0)
    in_feet = server.autocad_draw_wall_window("W1", wall_start=[0, 100], wall_end=[240, 100], width=5, offset=10, unit="ft")
    assert in_feet["window"]["width"] == pytest.approx(60.0) and in_feet["window"]["offset"] == pytest.approx(120.0)


def test_window_without_trim_keeps_the_wall_and_the_call_draws_straight_away(metric):
    wall = _wall()
    result = server.autocad_draw_wall_window("W1", wall_handle=wall["handle"], trim_wall=False)
    assert result["dry_run"] is False and "trimmed_wall" not in result and "would_replace_wall" not in result
    assert server.autocad_get_entity(wall["handle"])["entity"]["layer"] == "A-WALL"  # still there
    doc = _read(metric)
    assert _layers(doc) == {"A-WALL": 1, "A-GLAZ": 5, "A-GLAZ-SILL": 2, "A-GLAZ-IDEN": 1}  # 2 jambs + 2 glass + 1 mullion


def test_window_refusals_change_nothing(metric):
    wall = _wall()
    line = server.autocad_draw_line([0, 100], [3000, 100])
    before = server.autocad_drawing_summary()["model_space_entities"]
    for kwargs, needle in (
            ({"wall_handle": line["handle"], "dry_run": False}, "closed polyline"),
            ({"wall_handle": wall["handle"], "offset": 300, "dry_run": False}, "past the wall"),
            ({"wall_handle": wall["handle"], "width": 6000, "dry_run": False}, "does not fit"),
            ({"wall_handle": wall["handle"], "thickness": 100}, "not both"),
            ({"wall_handle": wall["handle"], "wall_start": [0, 0]}, "not both"),
            ({"wall_start": [0, 0]}, "both wall_start and wall_end"),
            ({}, "wall_handle"),
            ({"wall_start": [0, 0], "wall_end": [0, 0]}, "must differ"),
            ({"wall_start": [0, 0], "wall_end": [100, 0]}, "thick"),
            ({"wall_handle": wall["handle"], "window_type": "W9"}, "W1"),
            ({"wall_handle": wall["handle"], "tag_side": "top"}, "tag_side"),
            ({"wall_handle": wall["handle"], "unit": "furlong"}, "unit"),
            ({"wall_handle": "FFFF"}, "No model-space entity"),
    ):
        with pytest.raises(ToolError) as info:
            server.autocad_draw_wall_window(**kwargs)
        assert needle in _error(info)["message"], (kwargs, _error(info))
    assert server.autocad_drawing_summary()["model_space_entities"] == before
    assert server.autocad_get_entity(wall["handle"])["entity"]["handle"] == wall["handle"]


def test_a_failed_deletion_is_reported_with_the_handles_to_clean_up(metric, monkeypatch):
    wall = _wall()

    def refuse(handles, dry_run=True):
        raise RuntimeError("AutoCAD refused")

    monkeypatch.setattr(server.backend(), "delete_entities", refuse)
    with pytest.raises(ToolError) as info:
        server.autocad_draw_wall_window("W1", wall_handle=wall["handle"], dry_run=False)
    error = _error(info)
    assert error["code"] == "E_VERIFICATION_FAILED" and wall["handle"] in error["message"]
    assert error["details"]["wall_handle"] == wall["handle"] and len(error["details"]["new_wall_handles"]) == 2
    # nothing is hidden: the drawing holds the original wall, the two pieces, glass, sills and the tag
    assert server.autocad_drawing_summary()["model_space_entities"] == 1 + 2 + 3 + 2 + 1


def test_a_deletion_that_cannot_be_verified_is_an_error_too(metric, monkeypatch):
    wall = _wall()
    monkeypatch.setattr(server.backend(), "delete_entities", lambda handles, dry_run=True: {"verified": False})
    with pytest.raises(ToolError) as info:
        server.autocad_draw_wall_window("W1", wall_handle=wall["handle"], dry_run=False)
    assert _error(info)["code"] == "E_VERIFICATION_FAILED" and "could not be verified" in _error(info)["message"]


def test_window_on_something_that_is_not_a_straight_wall_is_refused(metric):
    box = server.autocad_draw_polyline([[0, 0], [4000, 0], [3000, 200], [0, 200]], closed=True, layer="A-WALL")
    with pytest.raises(ToolError) as info:
        server.autocad_draw_wall_window("W1", wall_handle=box["handle"])
    assert "not a straight wall outline" in _error(info)["message"]
    rectangle = server.autocad_draw_rectangle(base_point=[0, 1000], width=4000, height=200, layer="A-WALL")
    done = server.autocad_draw_wall_window("W1", wall_handle=rectangle["handle"], dry_run=False)
    assert done["trimmed_wall"]["deleted"] is True and len(done["trimmed_wall"]["new_handles"]) == 2


def test_window_layer_names_follow_the_chosen_layer(metric):
    server.autocad_draw_wall_window("W1", wall_start=[0, 0], wall_end=[5000, 0], layer="W-GLAZ")
    assert set(_layers(_read(metric))) == {"A-WALL", "W-GLAZ", "W-GLAZ-SILL", "W-GLAZ-IDEN"}


# ======= furniture =======


@pytest.mark.parametrize("kind,count,size", [
    ("bed", 5, (1500, 2000)), ("dining_table", 9, (1200, 1600)), ("sofa_set", 18, (3100, 2075)),
    ("wc", 8, (450, 700)), ("kitchen_countertop", 10, (2400, 600)),
])
def test_furniture_is_stamped_on_a_furn_centred_on_the_position(metric, kind, count, size):
    result = server.autocad_place_architectural_block(kind, [5000, 3000])
    assert result["verified"] is True and result["entity_count"] == count and result["generator"] == "furniture"
    footprint = result["furniture"]["footprint"]
    assert (footprint["width"], footprint["depth"]) == pytest.approx(size)
    doc = _read(metric)
    assert _layers(doc) == {"A-FURN": count} and doc.layers.get("A-FURN").color == 30
    xs = [c[0] for c in footprint["corners"]]
    ys = [c[1] for c in footprint["corners"]]
    assert ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2) == pytest.approx((5000, 3000))


def test_furniture_geometry_is_inside_its_reported_footprint(metric):
    result = server.autocad_place_architectural_block("bed", [0, 0], rotation_degrees=90)
    corners = result["furniture"]["footprint"]["corners"]
    box = (min(c[0] for c in corners), min(c[1] for c in corners), max(c[0] for c in corners), max(c[1] for c in corners))
    assert box == pytest.approx((-1000, -750, 1000, 750))  # a 1500 x 2000 bed turned to lie along X
    for entity in _on(_read(metric), "A-FURN", "LWPOLYLINE"):
        for x, y in _points(entity):
            assert box[0] - 1e-6 <= x <= box[2] + 1e-6 and box[1] - 1e-6 <= y <= box[3] + 1e-6


def test_furniture_variants_seats_labels_and_units(metric):
    server.autocad_place_architectural_block("bed", [0, 0], variant="single", label=True)
    server.autocad_place_architectural_block("dining_table", [5000, 0], seats=8, label=True)
    server.autocad_place_architectural_block("kitchen_countertop", [10000, 0], variant="l_left", return_length=2.4,
                                             unit="m")
    doc = _read(metric)
    assert len(_on(doc, "A-FURN", "LWPOLYLINE")) == (4 + 1) + (1 + 8 * 2) + 1 + 2  # bed, table + chairs, counter + 2 bowls
    labels = {t.text: t.dxf.char_height for t in _on(doc, "A-FURN-TEXT", "MTEXT")}
    assert labels == {"BED": pytest.approx(150.0), "DINING TABLE": pytest.approx(150.0)}
    counter = [e for e in _on(doc, "A-FURN", "LWPOLYLINE") if len(e.get_points()) == 6][0]
    assert max(y for _, y in _points(counter)) - min(y for _, y in _points(counter)) == pytest.approx(2400.0)


def test_furniture_sizes_and_label_follow_an_inch_drawing(imperial):
    result = server.autocad_place_architectural_block("bed", [0, 0], label=True)
    assert (result["furniture"]["footprint"]["width"], result["furniture"]["footprint"]["depth"]) == (60.0, 80.0)
    wc = server.autocad_place_architectural_block("wc", [200, 0])
    assert wc["furniture"]["footprint"]["depth"] == 28.0
    doc = _read(imperial)
    assert _on(doc, "A-FURN-TEXT", "MTEXT")[0].dxf.char_height == pytest.approx(6.0)
    arcs = _on(doc, "A-FURN", "ARC")
    assert len(arcs) == 2 and arcs[0].dxf.radius == pytest.approx(7.0)  # half of a 14 in bowl


def test_furniture_dry_run_draws_nothing(metric):
    result = server.autocad_place_architectural_block("sofa_set", [0, 0], dry_run=True)
    assert result["dry_run"] is True and result["plan"]["primitive_count"] == 18
    assert server.autocad_drawing_summary()["model_space_entities"] == 0


def test_a_standard_block_from_the_drawing_is_inserted_instead_of_the_shape(metric):
    doc = server.backend()._doc  # a block library entry, defined the way a template would define it
    block = doc.blocks.new("BED_DOUBLE")
    block.add_lwpolyline([(0, 0), (1500, 0), (1500, 2000), (0, 2000)], close=True)
    dry = server.autocad_place_architectural_block("bed", [3000, 2000], block_name="BED_DOUBLE", dry_run=True)
    assert dry["dry_run"] is True and dry["block_name"] == "BED_DOUBLE"
    assert server.autocad_drawing_summary()["model_space_entities"] == 0
    result = server.autocad_place_architectural_block("bed", [3000, 2000], rotation_degrees=90, block_name="BED_DOUBLE",
                                                      scale=2.0)
    assert result["generator"] == "furniture_block" and result["block"] == "BED_DOUBLE" and result["verified"] is True
    assert result["state"]["executed"] is True and result["scale"] == 2.0 and result["rotation_degrees"] == 90.0
    reference = _on(_read(metric), "A-FURN", "INSERT")[0]
    assert reference.dxf.name == "BED_DOUBLE" and (reference.dxf.xscale, reference.dxf.rotation) == (2.0, 90.0)
    assert tuple(reference.dxf.insert)[:2] == (3000.0, 2000.0)


def test_block_name_refusals(metric):
    for kwargs, code, needle in (
            ({"block_name": "NOPE"}, "E_BLOCK_NOT_FOUND", "NOPE"),
            ({"block_name": "NOPE", "dry_run": True}, "E_BLOCK_NOT_FOUND", "NOPE"),
            ({"block_name": "NOPE", "width": 1000}, "E_INVALID_INPUT", "width"),
            ({"block_name": "NOPE", "label": True}, "E_INVALID_INPUT", "label"),
            ({"block_name": "NOPE", "scale": 0}, "E_INVALID_INPUT", "scale"),
            ({"block_name": "NOPE", "scale": -1, "dry_run": True}, "E_INVALID_INPUT", "scale"),
    ):
        with pytest.raises(ToolError) as info:
            server.autocad_place_architectural_block("bed", [0, 0], **kwargs)
        assert _error(info)["code"] == code and needle in _error(info)["message"], kwargs
    assert server.autocad_drawing_summary()["model_space_entities"] == 0


def test_furniture_refusals_change_nothing(metric):
    for args, kwargs, needle in (
            (("piano", [0, 0]), {}, "block_type"), (("bed", [0, 0]), {"variant": "queen"}, "variant"),
            (("wc", [0, 0]), {"seats": 2}, "seats"), (("dining_table", [0, 0]), {"seats": 3}, "even"),
            (("kitchen_countertop", [0, 0]), {"width": 1000}, "too small"), (("bed", [0, 0]), {"unit": "x"}, "unit"),
            (("bed", "here"), {}, "position"),
    ):
        with pytest.raises(ToolError) as info:
            server.autocad_place_architectural_block(*args, **kwargs)
        assert _error(info)["code"] == "E_INVALID_INPUT" and needle in _error(info)["message"], (args, kwargs)
    assert server.autocad_drawing_summary()["model_space_entities"] == 0


# ======= all four together, the surface, and a real stdio session =======


def test_macros_work_together_and_the_drawing_passes_the_checks(metric):
    server.autocad_generate_floor_plan(rooms=[{"name": "Living", "x": 0, "y": 0, "width": 6, "depth": 4}], unit="m",
                                       windows="none", dimensions=False)
    server.autocad_draw_column_grid(at_wall_intersections=True)
    server.autocad_draw_staircase([8000, 0], 16)
    wall = _wall((0, 6000), (6000, 6000), layer="A-WALL-EXT")
    server.autocad_draw_wall_window("W2", wall_handle=wall["handle"], dry_run=False)
    server.autocad_place_architectural_block("bed", [3000, 2000])
    check = server.autocad_check_drawing()
    assert check["status"] == "ok" and check["entity_count"] > 60
    doc = _read(metric)
    assert {"COLUMNS", "A-FLOR-TRED", "A-GLAZ", "A-FURN", "A-WALL-EXT"} <= set(_layers(doc))
    validation = server.autocad_validate_dxf_file(path=str(metric / "out.dxf"))
    assert validation["valid"] is True


def test_capabilities_list_the_macros_on_both_backends(headless):
    tools = {t["name"]: t for t in server.autocad_get_capabilities()["tools"]}
    for name in ("autocad_draw_staircase", "autocad_draw_column_grid", "autocad_draw_wall_window",
                 "autocad_place_architectural_block"):
        assert tools[name]["backends"] == ["com", "dxf"] and tools[name]["toolset"] == "architecture"
    assert tools["autocad_draw_wall_window"]["kind"] == "destructive"
    assert tools["autocad_draw_wall_window"]["annotations"]["destructive_hint"] is True
    assert tools["autocad_draw_staircase"]["kind"] == "write"


def test_layer_standard_resource_lists_the_macro_layers(headless):
    contents = asyncio.run(server.server.read_resource("autocad://layer-standard"))
    data = json.loads(list(contents)[0].content)
    assert {"A-FLOR-TRED", "A-FLOR-HRAL", "COLUMNS", "A-GLAZ-SILL", "A-FURN"} <= set(data["macros"])
    assert data["macros"]["COLUMNS"]["color_index"] == 5 and data["macros"]["A-FURN"]["color_index"] == 30


async def _stdio_macros(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, "AUTOCAD_MCP_BACKEND": "dxf", "AUTOCAD_MCP_OUTPUT_DIR": str(tmp_path)}
    params = StdioServerParameters(command=sys.executable, args=[str(Path(server.__file__))], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            await client.call_tool("autocad_create_new_drawing", {})
            await client.call_tool("autocad_set_drawing_units", {"preset": "metric_mm"})
            stair = await client.call_tool("autocad_draw_staircase",
                                           {"start_point": [0, 0], "riser_count": 12, "direction": "DN"})
            columns = await client.call_tool("autocad_draw_column_grid", {"points": [[0, 0], [4000, 0]]})
            window = await client.call_tool("autocad_draw_wall_window", {"wall_start": [0, 0], "wall_end": [5000, 0]})
            bed = await client.call_tool("autocad_place_architectural_block", {"block_type": "bed", "position": [0, 0]})
            refused = await client.call_tool("autocad_draw_wall_window", {})
            bad_count = await client.call_tool("autocad_draw_staircase", {"start_point": [0, 0], "riser_count": 1})
            saved = await client.call_tool("autocad_save_drawing", {"path": str(tmp_path / "macros.dxf")})
            return stair, columns, window, bed, refused, bad_count, saved


def test_macros_over_a_real_stdio_session(tmp_path):
    stair, columns, window, bed, refused, bad_count, saved = asyncio.run(_stdio_macros(tmp_path))
    for response in (stair, columns, window, bed, saved):
        assert response.is_error is False, response.content[0].text
    assert json.loads(stair.content[0].text)["staircase"]["note"] == "DN 12R"
    assert json.loads(columns.content[0].text)["column_count"] == 2
    assert json.loads(window.content[0].text)["window"]["type"] == "W1"
    assert json.loads(bed.content[0].text)["furniture"]["footprint"]["width"] == pytest.approx(1500)
    for response in (refused, bad_count):
        assert response.is_error is True
        assert json.loads(response.content[0].text)["error"]["code"] == "E_INVALID_INPUT"
    doc = ezdxf.readfile(str(tmp_path / "macros.dxf"))
    assert {"A-FLOR-TRED", "COLUMNS", "A-GLAZ", "A-FURN"} <= set(_layers(doc))
