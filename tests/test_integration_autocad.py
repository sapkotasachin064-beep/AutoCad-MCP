"""Integration tests against a REAL running AutoCAD 2021+. No mocks here --
every call in this file is a genuine COM round trip.

These are skipped (not faked as passing) when AutoCAD is not installed, not
running, or not a supported release. Launch AutoCAD yourself first:

    python -c "import sys; sys.path.insert(0,'src/MCP'); from autocad import connection; print(connection.launch_and_wait())"

then run:

    python -m pytest tests/test_integration_autocad.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "MCP"))

from autocad import connection, db, editing, entities, layers, scanning


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
