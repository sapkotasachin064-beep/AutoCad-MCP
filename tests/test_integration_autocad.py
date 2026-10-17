"""Integration tests against a REAL running AutoCAD 2021+. No mocks here --
every call in this file is a genuine COM round trip.

These are skipped (not faked as passing) when AutoCAD is not installed, not
running, or not a supported release. Launch AutoCAD yourself first:

    python -c "import sys; sys.path.insert(0,'src'); from backends import com_engine as cad_engine; print(cad_engine.launch_and_wait())"

then run:

    python -m pytest tests/test_integration_autocad.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from backends import com_engine as connection
from core import db
from tools import drawing, editing
from tools import output as scanning

layers = entities = drawing


def _autocad_available() -> bool:
    status = connection.get_status()
    return status.connected and status.supported


skip_reason = "BLOCKED: AutoCAD is not running/connected/supported release. See module docstring to launch it first."
requires_autocad = pytest.mark.skipif(not _autocad_available(), reason=skip_reason)


@pytest.fixture
def fresh_drawing(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCAD_MCP_DB_PATH", str(tmp_path / "integration.db"))
    result = entities.create_new_drawing()
    assert result["status"] == "ok"
    doc_name = result["drawing_name"]
    yield result
    with connection.com_initialized():
        app = connection.get_connected_app()
        for i in range(app.Documents.Count):
            doc = app.Documents.Item(i)
            if doc.Name == doc_name:
                doc.Close(False)
                break


@requires_autocad
def test_create_new_drawing_becomes_active(fresh_drawing):
    assert fresh_drawing["drawing_identity"].startswith("unsaved:")


@requires_autocad
def test_draw_line_creates_real_entity(fresh_drawing):
    result = entities.draw_line([0, 0, 0], [100, 100, 0])
    assert result["status"] == "ok"
    assert result["handle"]

    with connection.com_initialized():
        app = connection.get_connected_app()
        doc = connection.get_active_document(app)
        entity = doc.HandleToObject(result["handle"])
        assert entity.ObjectName == "AcDbLine"
        assert tuple(entity.StartPoint) == (0.0, 0.0, 0.0)


@requires_autocad
def test_draw_circle_and_create_layer(fresh_drawing):
    layer_result = layers.create_layer("MCP_TEST_LAYER", color_index=3)
    assert layer_result["status"] == "ok"

    circle_result = entities.draw_circle([10, 10, 0], 5, layer="MCP_TEST_LAYER")
    assert circle_result["status"] == "ok"
    assert circle_result["layer"] == "MCP_TEST_LAYER"

    with connection.com_initialized():
        app = connection.get_connected_app()
        doc = connection.get_active_document(app)
        entity = doc.HandleToObject(circle_result["handle"])
        assert entity.ObjectName == "AcDbCircle"
        assert entity.Radius == pytest.approx(5.0)
        assert entity.Layer == "MCP_TEST_LAYER"


@requires_autocad
def test_draw_rectangle_and_polyline(fresh_drawing):
    rect = entities.draw_rectangle(corner1=[0, 0], corner2=[20, 10])
    assert rect["status"] == "ok"
    assert rect["closed"] is True

    pline = entities.draw_polyline([[0, 0], [5, 5], [10, 0]], closed=False)
    assert pline["status"] == "ok"
    assert pline["closed"] is False


@requires_autocad
def test_draw_text(fresh_drawing):
    result = entities.draw_text("MCP V0.2.0", [0, 0], 2.5, rotation_degrees=90)
    assert result["status"] == "ok"

    with connection.com_initialized():
        app = connection.get_connected_app()
        doc = connection.get_active_document(app)
        entity = doc.HandleToObject(result["handle"])
        assert entity.TextString == "MCP V0.2.0"


@requires_autocad
def test_move_rotate_copy_entity(fresh_drawing):
    line = entities.draw_line([0, 0, 0], [10, 0, 0])
    handle = line["handle"]

    moved = editing.move_entity(handle, [5, 5, 0])
    assert moved["status"] == "ok"

    rotated = editing.rotate_entity(handle, [0, 0, 0], 90)
    assert rotated["status"] == "ok"

    copied = editing.copy_entity(handle, [100, 100, 0])
    assert copied["status"] == "ok"
    assert copied["new_handle"] != handle


@requires_autocad
def test_highlight_entity_temporary_preserves_color(fresh_drawing):
    line = entities.draw_line([0, 0, 0], [10, 0, 0])
    handle = line["handle"]

    with connection.com_initialized():
        app = connection.get_connected_app()
        doc = connection.get_active_document(app)
        original_color = doc.HandleToObject(handle).Color

    result = editing.highlight_entity(handle, method="temporary")
    assert result["status"] == "ok"
    assert result["color"] == original_color  # untouched by temporary highlight

    cleared = editing.highlight_entity(handle, method="temporary", clear=True)
    assert cleared["highlighted"] is False


@requires_autocad
def test_highlight_entity_persistent_changes_color(fresh_drawing):
    line = entities.draw_line([0, 0, 0], [10, 0, 0])
    handle = line["handle"]

    result = editing.highlight_entity(handle, method="persistent", color=4)
    assert result["status"] == "ok"
    assert result["color"] == 4

    with connection.com_initialized():
        app = connection.get_connected_app()
        doc = connection.get_active_document(app)
        assert doc.HandleToObject(handle).Color == 4


@requires_autocad
def test_highlight_text_matches_does_not_modify_text(fresh_drawing):
    text_result = entities.draw_text("PMC-3M-UNIT-TEST", [0, 0], 2.5)
    handle = text_result["handle"]

    result = editing.highlight_text_matches("PMC-3M", method="persistent", color=2)
    assert result["status"] == "ok"
    assert result["match_count"] >= 1
    assert any(m["handle"] == handle for m in result["matches"])

    with connection.com_initialized():
        app = connection.get_connected_app()
        doc = connection.get_active_document(app)
        assert doc.HandleToObject(handle).TextString == "PMC-3M-UNIT-TEST"


@requires_autocad
def test_count_text_patterns_literal_and_regex(fresh_drawing):
    entities.draw_text("DEVICE-P14", [0, 0], 2.5)
    entities.draw_text("DEVICE-P02", [0, 10], 2.5)
    entities.draw_text("unrelated", [0, 20], 2.5)

    literal = scanning.count_text_patterns("DEVICE-")
    assert literal["match_count"] == 2

    regex = scanning.count_text_patterns(r"DEVICE-P\d+", use_regex=True)
    assert regex["match_count"] == 2


@requires_autocad
def test_scan_all_entities_and_execute_query_round_trip(fresh_drawing, tmp_path):
    line = entities.draw_line([0, 0, 0], [10, 10, 0])
    circle = entities.draw_circle([5, 5, 0], 3)

    scan_result = scanning.scan_all_entities()
    assert scan_result["status"] == "ok"
    assert scan_result["scanned_count"] >= 2

    db_path = scan_result["db_path"]
    query_result = db.execute_readonly_query(
        db_path, "SELECT handle, object_name FROM entities WHERE handle IN (?, ?)", [line["handle"], circle["handle"]]
    )
    found = {row["handle"]: row["object_name"] for row in query_result.rows}
    assert found[line["handle"]] == "AcDbLine"
    assert found[circle["handle"]] == "AcDbCircle"

    with pytest.raises(db.QueryRejected):
        db.execute_readonly_query(db_path, "DELETE FROM entities")


# ======= V0.3.0 live tests =======
#
# Same rules as above: every test works in its own fresh unsaved drawing
# (fresh_drawing closes it without saving), writes files only under tmp_path,
# and is skipped -- never faked -- when AutoCAD is not running. These are the
# tests that turn the V0.3.0 COM tools from "mock-tested" into "live-verified".

import math  # noqa: E402

from core import session  # noqa: E402
from tools import annotation, civil, documents, output  # noqa: E402

blocks = drawing
modify = query = editing


@pytest.fixture
def clean_session():
    session.unpin_document()
    session.set_units_override(None)
    yield
    session.unpin_document()
    session.set_units_override(None)


@requires_autocad
def test_v030_list_drawings_and_units(fresh_drawing, clean_session):
    listed = documents.list_drawings()
    active = [d for d in listed["drawings"] if d["active"]]
    assert active and active[0]["identity"] == fresh_drawing["drawing_identity"]
    result = documents.set_drawing_units("metric_mm")
    assert result["insunits"] == 4
    entities.draw_line([0, 0], [1000, 0])  # the session preset must stick (no flip back to inches)
    with connection.com_initialized():
        doc = connection.get_active_document(connection.get_connected_app(), for_write=False)
        assert connection.read_insunits(doc) == 4


@requires_autocad
def test_v030_summary_list_and_detail(fresh_drawing, clean_session):
    line = entities.draw_line([0, 0], [3, 4], layer="MCP_Q")
    entities.draw_circle([10, 10], 2)
    summary = query.drawing_summary()
    assert summary["counts_by_type"].get("LINE") == 1 and summary["counts_by_type"].get("CIRCLE") == 1
    listed = query.list_entities(entity_types=["LINE"], layers=["MCP_Q"])
    assert [e["handle"] for e in listed["entities"]] == [line["handle"]]
    detail = query.get_entity(line["handle"])["entity"]
    assert detail["length"] == pytest.approx(5.0)
    snap = query.snapshot_entities()
    assert snap["total"] == 2


@requires_autocad
def test_v030_modify_suite(fresh_drawing, clean_session):
    handle = entities.draw_line([0, 0], [10, 0])["handle"]
    assert modify.scale_entity(handle, [0, 0], 2.0)["verified"] is True
    assert modify.mirror_entity(handle, [0, 5], [10, 5])["new_handle"]
    assert len(modify.offset_entity(handle, 1.0)["new_handles"]) == 1
    assert len(modify.array_rectangular(handle, 2, 2, 5.0, 5.0)["new_handles"]) == 3
    props = modify.set_entity_properties([handle], layer="MCP_PROPS", color_index=3, lineweight=35)
    assert props["verified"] is True
    plan = modify.delete_entities([handle])
    assert plan["dry_run"] is True
    done = modify.delete_entities([handle], dry_run=False)
    assert done["verified"] is True


@requires_autocad
def test_v030_annotation_live(fresh_drawing, clean_session):
    arc = annotation.draw_arc([0, 0], 5, 0, 90)
    assert arc["end_angle_degrees"] == pytest.approx(90)
    assert annotation.draw_mtext(r"Kitchen\P12 m2", [0, 0], 2.5, width=30)["verified"] is True
    aligned = annotation.add_dimension("aligned", [0, 0], [3, 4], [-2, 2])
    assert aligned["measurement"] == pytest.approx(5.0)
    linear = annotation.add_dimension("linear", [0, 0], [3, 4], [0, -3], rotation_degrees=0)
    assert linear["measurement"] == pytest.approx(3.0)
    # Settles the AddHatch pattern-type constant live: the pattern must read back as ANSI31.
    hatch = annotation.add_hatch(boundary_points=[[0, 0], [4, 0], [4, 3], [0, 3]], pattern="ANSI31")
    assert hatch["pattern"] == "ANSI31" and hatch["area"] == pytest.approx(12.0)


@requires_autocad
def test_v030_blocks_live(fresh_drawing, clean_session):
    with connection.com_initialized():
        doc = connection.get_active_document(connection.get_connected_app())
        block = doc.Blocks.Add(connection.point_variant((0.0, 0.0, 0.0)), "MCP_TAG")
        block.AddCircle(connection.point_variant((0.0, 0.0, 0.0)), 1.0)
        # AddAttribute(Height, Mode, Prompt, InsertionPoint, Tag, Value)
        block.AddAttribute(0.5, 0, "Mark", connection.point_variant((0.0, -1.5, 0.0)), "MARK", "?")
    inserted = blocks.insert_block("MCP_TAG", [5, 5], attributes={"MARK": "D1"})
    assert inserted["attributes"]["MARK"] == "D1"
    updated = blocks.set_block_attributes(inserted["handle"], {"MARK": "D2"})
    assert updated["verified"] is True
    assert any(b["name"] == "MCP_TAG" for b in blocks.list_blocks()["blocks"])


@requires_autocad
def test_v030_export_and_plot_live(fresh_drawing, clean_session, tmp_path):
    entities.draw_rectangle(corner1=[0, 0], corner2=[420, 297])
    exported = output.export_dxf(str(tmp_path / "copy.dxf"))
    assert exported["verified"] is True and exported["document_unchanged"] is True
    plotted = output.plot_pdf(str(tmp_path / "sheet.pdf"))
    assert plotted["verified"] is True and plotted["file"]["size_bytes"] > 0
    assert plotted["layout_settings_restored"] is True
    layouts = output.list_layouts()
    assert any(lo["is_model"] for lo in layouts["layouts"])


@requires_autocad
def test_v030_save_as_then_close(fresh_drawing, clean_session, tmp_path):
    entities.draw_line([0, 0], [1, 1])
    saved = documents.save_drawing(str(tmp_path / "saved.dwg"))
    assert saved["verified"] is True and saved["drawing_identity"].endswith("saved.dwg")
    closed = documents.close_drawing()
    assert closed["verified"] is True


@requires_autocad
def test_v030_generators_live(fresh_drawing, clean_session):
    import server

    plan = server.autocad_generate_floor_plan(
        rooms=[{"name": "Living", "x": 0, "y": 0, "width": 15, "depth": 12},
               {"name": "Bed", "x": 15, "y": 0, "width": 12, "depth": 12}], unit="ft")
    assert plan["verified"] is True and len(plan["rooms"]) == 2
    grid = server.autocad_draw_structural_grid(x_spacings=[15, 12], y_spacings=[12], unit="ft",
                                               origin=[0, -400])
    assert grid["verified"] is True
    legacy = server.autocad_generate_2d_floor_plan()
    assert legacy["verified"] is True and legacy["entity_count"] == 50
    check = server.autocad_check_drawing()
    assert check["entity_count"] > 0 and not math.isnan(check["issue_count"])


@requires_autocad
def test_architectural_macros_live(fresh_drawing, clean_session):
    """Written without a live run: the first run against AutoCAD is the first live evidence for these four
    tools (the catalog lists them as `tested`, not `verified`, until it is recorded in data_live.py)."""
    import server

    stair = server.autocad_draw_staircase([0, 0], 12, direction="DN")
    assert stair["verified"] is True and stair["entity_count"] == 30
    grid = server.autocad_draw_column_grid(x_spacings=[4000, 4000], y_spacings=[3000], unit="mm", origin=[100, 0])
    assert grid["verified"] is True and grid["column_count"] == 6
    wall = server.autocad_draw_wall([0, 300], [240, 300])
    window = server.autocad_draw_wall_window("W1", wall_handle=wall["handle"], dry_run=False)
    assert window["verified"] is True and window["trimmed_wall"]["deleted"] is True
    assert len(window["trimmed_wall"]["new_handles"]) == 2
    placed = [server.autocad_place_architectural_block(kind, [600, 100 + 100 * i], label=True)
              for i, kind in enumerate(("bed", "dining_table", "sofa_set", "wc", "kitchen_countertop"))]
    assert all(p["verified"] is True for p in placed)
    takeoff = server.autocad_quantity_takeoff()
    assert takeoff["layers"]["A-WALL"]["walls"]["count"] == 2
    # AutoCAD accepted the text height, arrow, extension and precision set on every dimension
    refused = [n for r in (stair, grid, window, *placed) for n in r.get("notices", [])
               if n["kind"] == "dimension_size_not_applied"]
    assert refused == []


# ======= civil =======


@requires_autocad
def test_v030_civil_live(fresh_drawing, clean_session):
    polyline = entities.draw_polyline([[0, 0], [100, 0], [100, 100]])
    result = civil.alignment_station(polyline["handle"], [[50, -10], [110, 50]], start_station=1000.0)
    first, second = result["points"]
    assert first["station"] == pytest.approx(1050.0) and first["offset"] == pytest.approx(10.0)
    assert second["station"] == pytest.approx(1150.0) and second["offset"] == pytest.approx(10.0)
    back = civil.station_point(polyline["handle"], [1050.0], offset=2.0, start_station=1000.0)
    assert back["stations"][0]["point"] == pytest.approx([50.0, -2.0, 0.0])
    assert back["stations"][0]["tangent_angle_degrees"] == pytest.approx(0.0)

    placed = civil.place_points([[0, 0, 10], [10, 0, 12], [20, 0, 14], [30, 0, 16]], layer="MCP_TOPO",
                                label=False)
    assert placed["verified"] is True and placed["count"] == 4
    ground = entities.draw_line([0, 0], [30, 0])
    profile = civil.ground_profile(ground["handle"], 10.0, layer="MCP_TOPO")
    assert [row["elevation"] for row in profile["stations"]] == pytest.approx([10, 12, 14, 16])

    corners = ((0, 0), (4, 0), (4, 4), (0, 4))
    civil.place_points([(x, y, 0.0) for x, y in corners], layer="MCP_EG", label=False)
    civil.place_points([(x, y, 0.5) for x, y in corners], layer="MCP_FG", label=False)
    volumes = civil.surface_volumes("MCP_EG", "MCP_FG", 1.0)
    assert volumes["fill_volume"] == pytest.approx(8.0) and volumes["cut_volume"] == pytest.approx(0.0)

    first_pipe = entities.draw_line([0, 0, 0], [10, 0, 0])
    second_pipe = entities.draw_line([5, -5, -3], [5, 5, -3])
    clearance = civil.pipe_clearance(first_pipe["handle"], second_pipe["handle"], 0.5, 0.5)
    assert clearance["minimum_distance"] == pytest.approx(3.0)
    assert clearance["surface_clearance"] == pytest.approx(2.5)
    assert clearance["crossings"][0]["vertical_gap"] == pytest.approx(-3.0)
