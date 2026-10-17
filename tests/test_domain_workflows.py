"""Pure engineering logic: room floor plans, grids, stairs, sheets, QC,
takeoff and comparison. No CAD engine involved (RecordingTarget only)."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from backends.targets import RecordingTarget, emit
from core.errors import CadError
from domain import analysis, architecture, units

floorplan = grids = stairs = sheets = architecture
qc = takeoff = diff = analysis

FT, IN, MM, M = (units.unit_code(u) for u in ("ft", "in", "mm", "m"))

L_SHAPE = [
    {"name": "Living", "x": 0, "y": 0, "width": 5, "depth": 4},
    {"name": "Kitchen", "x": 5, "y": 0, "width": 3, "depth": 4},
    {"name": "Bed", "x": 0, "y": 4, "width": 5, "depth": 3.5},
]


# ======= floor plan from rooms =======


def test_room_plan_walls_doors_windows_and_schedules():
    plan = floorplan.plan_room_floor_plan(L_SHAPE, M, MM)
    meta = plan.meta
    # Outline of the L: 8 exterior runs (a run is split where the owning room changes:
    # south 2, east 1, kitchen top 1, bed east 1, bed top 1, west 2); shared edges: 2.
    assert meta["walls"]["exterior"] == 8
    assert meta["walls"]["interior"] == 2
    kinds = [d["kind"] for d in meta["doors"]]
    assert kinds.count("main") == 1 and kinds.count("interior") == 2
    assert meta["unreachable_rooms"] == []
    assert {w["room"] for w in meta["windows"]} == {"Living", "Kitchen", "Bed"}
    living = next(r for r in meta["rooms"] if r["name"] == "Living")
    # clear width = 5000 - 230/2 (west, exterior) - 115/2 (east, shared with kitchen)
    assert living["clear_width"] == pytest.approx(5000 - 115 - 57.5)
    assert "m²" in living["label"]
    target = RecordingTarget(insunits=MM)
    handles = emit(plan, target)
    assert len(handles) == len(plan.primitives) == target.count()


def test_room_plan_in_feet_converts_into_inch_drawing():
    rooms = [{"name": "A", "x": 0, "y": 0, "width": 12, "depth": 10}]
    plan = floorplan.plan_room_floor_plan(rooms, FT, IN, dimensions=False)
    xs = [p[0] for prim in plan.primitives if prim.kind == "polyline" for p in prim.points]
    assert max(xs) == pytest.approx(144 + 4.5)  # 12 ft wall line + half the 9" wall
    assert "ft²" in plan.meta["rooms"][0]["label"]


def test_room_plan_rejects_overlap_and_bad_doors():
    with pytest.raises(CadError):
        floorplan.plan_room_floor_plan([{"name": "A", "x": 0, "y": 0, "width": 4, "depth": 4},
                                        {"name": "B", "x": 3, "y": 3, "width": 4, "depth": 4}], M, MM)
    with pytest.raises(CadError):
        floorplan.plan_room_floor_plan(L_SHAPE, M, MM, doors=[{"between": ["Kitchen", "Bed"]}])  # share no wall
    with pytest.raises(CadError):
        floorplan.plan_room_floor_plan(L_SHAPE, M, MM, doors=[{"between": ["Living", "Garage"]}])
    with pytest.raises(CadError):
        floorplan.plan_room_floor_plan(L_SHAPE, M, MM, doors=[{"between": ["Living", "Kitchen"], "width": 10}])


def test_room_plan_reports_unreachable_rooms():
    rooms = L_SHAPE + [{"name": "Shed", "x": 20, "y": 20, "width": 2, "depth": 2}]
    assert floorplan.plan_room_floor_plan(rooms, M, MM).meta["unreachable_rooms"] == ["Shed"]


def test_room_names_must_be_unique():
    with pytest.raises(CadError):
        floorplan.plan_room_floor_plan(L_SHAPE + [{"name": "living", "x": 10, "y": 0, "width": 2, "depth": 2}], M, MM)


def test_floor_plan_dimensions_are_sized_from_the_room_label_height_in_any_unit():
    metric = floorplan.plan_room_floor_plan(L_SHAPE, M, MM)
    dims = [p for p in metric.primitives if p.kind == "dim_linear"]
    assert len(dims) == 2 and all(p.height == pytest.approx(150.0) for p in dims)
    imperial = floorplan.plan_room_floor_plan(L_SHAPE, M, IN)
    assert all(p.height == pytest.approx(6.0) for p in imperial.primitives if p.kind == "dim_linear")
    custom = floorplan.plan_room_floor_plan(L_SHAPE, M, MM, label_height=0.2)  # 0.2 m, in metres
    assert all(p.height == pytest.approx(200.0) for p in custom.primitives if p.kind == "dim_linear")
    bare = floorplan.plan_room_floor_plan(L_SHAPE, M, MM, dimensions=False)
    assert not [p for p in bare.primitives if p.kind == "dim_linear"]


def test_grid_dimensions_are_sized_from_the_bubble_text_height():
    plan = grids.plan_grid([4, 5, 4], [6, 6], M, MM)
    dims = [p for p in plan.primitives if p.kind == "dim_linear"]
    assert len(dims) == 7 and all(p.height == pytest.approx(350.0) for p in dims)
    custom = grids.plan_grid([4, 5], [6], M, MM, text_height=0.5)
    assert all(p.height == pytest.approx(500.0) for p in custom.primitives if p.kind == "dim_linear")


# ======= grid =======


def test_grid_lines_labels_columns_and_dimensions():
    plan = grids.plan_grid([4, 5, 4], [6, 6], M, MM, column_size=[0.3, 0.45])
    meta = plan.meta
    assert [x["label"] for x in meta["x_lines"]] == ["1", "2", "3", "4"]
    assert [y["label"] for y in meta["y_lines"]] == ["A", "B", "C"]
    assert meta["overall"] == {"x": pytest.approx(13000), "y": pytest.approx(12000)}
    assert len(meta["columns"]) == 12
    counts = plan.summary(0)["counts_by_kind"]
    assert counts["dim_linear"] == 3 + 1 + 2 + 1
    assert counts["hatch"] == 12


def test_grid_letters_skip_i_and_o_and_extend_past_z():
    labels = grids.letters(30)
    assert "I" not in labels and "O" not in labels
    assert labels[24] == "AA"
    assert grids.letters(10, skip=())[8] == "I"


# ======= stairs =======


def test_stair_metric_rule_of_thumb():
    d = stairs.design_stair(3000, MM)
    assert d["risers"] == 16 and d["riser_height"] == pytest.approx(187.5)
    assert d["tread_depth"] == pytest.approx(250.0) and d["treads"] == 15
    assert d["run_length"] == pytest.approx(3750.0)
    assert d["all_checks_pass"] is True
    assert d["limits_source"] == "rule_of_thumb_defaults_not_a_building_code"
    assert "local building code" in d["not_checked"]


def test_stair_with_callers_limits_and_failure_reported():
    d = stairs.design_stair(9, FT, max_riser=7.75 / 12, min_tread=10 / 12, tread=8 / 12)
    assert d["limits_source"] == "caller"
    assert d["all_checks_pass"] is False
    failed = {c["rule"] for c in d["checks"] if not c["ok"]}
    assert "going >= min_tread" in failed


def test_stair_plan_geometry():
    d = stairs.design_stair(3000, MM)
    plan = stairs.plan_stair(d, MM, MM, origin=(1000, 0))
    nosings = [p for p in plan.primitives if p.tag.startswith("stair:nosing")]
    assert len(nosings) == d["treads"] - 1
    with pytest.raises(CadError):
        stairs.plan_stair(d, MM, MM, direction_degrees=45)


# ======= sheets =======


def test_a3_sheet_at_1_100_in_mm_drawing():
    plan = sheets.plan_sheet("A3", 100, MM, fields={"project": "House", "title": "Ground floor"})
    assert plan.meta["sheet_size_drawing_units"] == [pytest.approx(42000), pytest.approx(29700)]
    texts = {p.tag: p for p in plan.primitives if p.kind == "mtext"}
    assert texts["title:value:project"].text == "House"
    assert texts["title:value:scale"].text == "1:100"
    assert texts["title:value:project"].height == pytest.approx(350)  # 3.5 mm at 1:100


def test_sheet_rejects_unknown_paper_and_fields():
    with pytest.raises(CadError):
        sheets.plan_sheet("B5", 50, MM)
    with pytest.raises(CadError):
        sheets.plan_sheet("A4", 50, MM, fields={"colour": "red"})


# ======= QC / takeoff / diff =======

SNAP = [
    {"handle": "1", "type": "LINE", "layer": "A-WALL", "points": [[0, 0, 0], [0, 0, 0]], "length": 0.0},
    {"handle": "2", "type": "LINE", "layer": "0", "points": [[0, 0, 0], [5, 0, 0]], "length": 5.0},
    {"handle": "3", "type": "LINE", "layer": "0", "points": [[5, 0, 0], [0, 0, 0]], "length": 5.0},
    {"handle": "4", "type": "POLYLINE3D", "layer": "A-WALL-EXT", "points": [[0, 0, 0], [10, 0, 0], [10, 0.2, 0], [0, 0.2, 0]],
     "closed": True, "length": 20.4},
    {"handle": "5", "type": "LWPOLYLINE", "layer": "A-WALL", "points": [[0, 0], [1, 0]], "closed": False, "length": 1.0},
    {"handle": "6", "type": "TEXT", "layer": "A-TEXT", "text": "  ", "insertion_point": [0, 0, 0], "height": 2.5},
    {"handle": "7", "type": "CIRCLE", "layer": "S-COLS", "center": [0, 0, 0], "radius": 0.15},
    {"handle": "8", "type": "INSERT", "layer": "A-DOOR", "block": "DOOR90", "insertion_point": [1, 1, 0]},
]


def test_qc_rules_fire_on_the_right_entities():
    result = qc.check(SNAP, layer_pattern=r"[A-Z]-[A-Z0-9-]+")
    rules = {(i["rule"], i.get("handle")) for i in result["issues"]}
    assert ("zero_length", "1") in rules
    assert ("duplicate", "3") in rules  # reversed copy of line 2
    assert ("empty_text", "6") in rules
    assert ("unclosed_wall_outline", "5") in rules
    assert ("on_layer_0", "2") in rules
    assert result["passed"] is False  # zero_length is an error


def test_takeoff_measures_layers_and_walls():
    result = takeoff.takeoff(SNAP, M, wall_height=3.0)
    wall = result["layers"]["A-WALL-EXT"]["walls"]
    assert wall["count"] == 1 and wall["length"] == pytest.approx(10.0)
    assert wall["volume_estimate"] == pytest.approx(10 * 0.2 * 3)
    assert result["layers"]["0"]["line_length"] == pytest.approx(10.0)
    assert result["layers"]["S-COLS"]["circle_area"] == pytest.approx(math.pi * 0.15 ** 2, abs=1e-6)
    assert result["layers"]["A-DOOR"]["blocks"] == {"DOOR90": 1}
    assert result["layers"]["0"]["metric"]["total_length_m"] == pytest.approx(10.0)


def test_diff_changed_added_removed_and_rehandled():
    old = [dict(e) for e in SNAP]
    new = [dict(e) for e in SNAP if e["handle"] not in ("6", "7")]
    new[1] = {**new[1], "layer": "A-WALL"}  # handle 2 moved to another layer
    new.append({**SNAP[6], "handle": "99"})  # circle 7 re-created with a new handle
    new.append({"handle": "100", "type": "LINE", "layer": "0", "points": [[9, 9, 0], [10, 10, 0]], "length": 1.4})
    result = diff.compare(old, new)
    assert result["summary"]["changed"] == 1 and result["changed"][0]["fields"] == ["layer"]
    assert result["summary"]["same_geometry_new_handle"] == 1
    assert [e["handle"] for e in result["removed"]] == ["6"]
    assert [e["handle"] for e in result["added"]] == ["100"]
    assert result["identical"] is False
    assert diff.compare(old, old)["identical"] is True
