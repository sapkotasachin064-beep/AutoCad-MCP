"""Headless DXF backend: real ezdxf documents and real files in tmp_path.
Each test reads the written DXF back with ezdxf, independently of the code
under test."""

import importlib.util
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

ezdxf = pytest.importorskip("ezdxf")

import db  # noqa: E402
from backends.dxf import DxfBackend  # noqa: E402
from core import session  # noqa: E402
from core.errors import CadError  # noqa: E402


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCAD_MCP_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOCAD_MCP_DB_PATH", str(tmp_path / "scan.db"))
    monkeypatch.delenv("AUTOCAD_MCP_UNITS", raising=False)
    session.unpin_document()
    session.set_units_override(None)
    b = DxfBackend()
    b.create_new_drawing()
    yield b
    session.unpin_document()
    session.set_units_override(None)


def test_new_drawing_gets_the_default_units_preset(backend):
    status = backend.get_status()
    assert status["document"]["identity"] == "unsaved:drawing1.dxf"
    summary = backend.drawing_summary()
    assert summary["units"]["insunits_name"] == "in" and summary["backend"] == "dxf"


def test_draw_save_and_read_back(backend, tmp_path):
    line = backend.draw_line([0, 0], [3, 4], layer="A-WALL")
    backend.draw_polyline([[0, 0], [10, 0], [10, 5]], closed=True)
    backend.draw_circle([5, 5], 2)
    backend.draw_text("ROOM", [1, 1], 2.5, rotation_degrees=15)
    backend.draw_arc([0, 0], 5, 0, 90)
    backend.draw_mtext("A\\PB", [2, 2], 3.0, width=40)
    backend.draw_rectangle(base_point=[0, 0], width=4, height=3)
    assert line["verified"] is True and line["state"] if "state" in line else True

    saved = backend.save_drawing(str(tmp_path / "plan.dxf"))
    assert saved["verified"] is True and saved["file"]["size_bytes"] > 0
    doc = ezdxf.readfile(str(tmp_path / "plan.dxf"))
    types = sorted(e.dxftype() for e in doc.modelspace())
    assert types == ["ARC", "CIRCLE", "LINE", "MTEXT", "POLYLINE", "POLYLINE", "TEXT"]
    assert doc.header["$INSUNITS"] == 1
    assert saved["drawing_identity"].startswith("path:")


def test_save_refuses_existing_file_and_never_saved_drawing(backend, tmp_path):
    with pytest.raises(CadError) as info:
        backend.save_drawing()
    assert info.value.code == "E_INVALID_INPUT"
    target = tmp_path / "keep.dxf"
    target.write_text("precious")
    with pytest.raises(CadError) as info:
        backend.save_drawing(str(target))
    assert info.value.code == "E_OUTPUT_EXISTS"
    assert target.read_text() == "precious"


def test_open_read_only_and_dwg_refusal(backend, tmp_path):
    backend.draw_line([0, 0], [1, 1])
    backend.save_drawing(str(tmp_path / "a.dxf"))
    other = DxfBackend()
    opened = other.open_drawing(str(tmp_path / "a.dxf"))
    assert opened["read_only"] is True and opened["audit"]["errors"] == 0
    other.draw_line([1, 1], [2, 2])
    with pytest.raises(CadError):
        other.save_drawing()  # read-only: must not overwrite its source
    dwg = tmp_path / "a.dwg"
    dwg.write_bytes(b"AC1032")
    with pytest.raises(CadError) as info:
        DxfBackend().open_drawing(str(dwg))
    assert info.value.code == "E_UNSUPPORTED_BACKEND"


def test_query_filters_pages_and_details(backend):
    backend.draw_line([0, 0], [3, 4], layer="A")
    backend.draw_circle([50, 50], 1, layer="B")
    backend.draw_text("T", [0, 0], 1, layer="B")
    page = backend.list_entities(layers=["b"])
    assert page["total"] == 2
    inside = backend.list_entities(bbox=[[-1, -1], [10, 10]])
    assert {e["type"] for e in inside["entities"]} == {"LINE", "TEXT"}
    handle = backend.list_entities(entity_types=["LINE"])["entities"][0]["handle"]
    assert backend.get_entity(handle)["entity"]["length"] == pytest.approx(5.0)


def test_editing_round_trip(backend):
    h = backend.draw_line([0, 0], [10, 0])["handle"]
    backend.move_entity(h, [1, 2, 0])
    backend.rotate_entity(h, [1, 2], 90)
    e = backend.get_entity(h)["entity"]
    assert e["points"][1][0] == pytest.approx(1.0) and e["points"][1][1] == pytest.approx(12.0)
    copy = backend.copy_entity(h, [5, 0, 0])["new_handle"]
    assert copy != h
    backend.scale_entity(h, [1, 2], 2.0)
    assert backend.get_entity(h)["entity"]["length"] == pytest.approx(20.0)
    assert backend.mirror_entity(h, [0, 0], [0, 10])["new_handle"]
    assert len(backend.array_rectangular(h, 2, 2, 5.0, 5.0)["new_handles"]) == 3
    offset = backend.offset_entity(backend.draw_circle([0, 0], 5)["handle"], 1.5)
    assert backend.get_entity(offset["new_handles"][0])["entity"]["radius"] == pytest.approx(6.5)


def test_delete_dry_run_then_real(backend):
    h = backend.draw_line([0, 0], [1, 1])["handle"]
    plan = backend.delete_entities([h])
    assert plan["dry_run"] is True and backend.drawing_summary()["model_space_entities"] == 1
    done = backend.delete_entities([h], dry_run=False)
    assert done["verified"] is True and backend.drawing_summary()["model_space_entities"] == 0


def test_dimensions_and_hatch(backend):
    aligned = backend.add_dimension("aligned", [0, 0], [3, 4], [-1, 2])
    linear = backend.add_dimension("linear", [0, 0], [3, 4], [0, -2], rotation_degrees=0)
    assert aligned["measurement"] == pytest.approx(5.0) and linear["measurement"] == pytest.approx(3.0)
    hatch = backend.add_hatch(boundary_points=[[0, 0], [4, 0], [4, 3], [0, 3]], pattern="ansi31")
    assert hatch["area"] == pytest.approx(12.0) and hatch["pattern"] == "ANSI31"
    with pytest.raises(CadError):
        backend.add_hatch(boundary_points=[[0, 0], [1, 0], [1, 1]], pattern="NOT_A_PATTERN")


def test_blocks_with_attributes(backend):
    doc = backend._doc
    block = doc.blocks.new("DOOR-TAG")
    block.add_circle((0, 0), 1)
    block.add_attdef("MARK", (0, 0), dxfattribs={"height": 1})
    inserted = backend.insert_block("DOOR-TAG", [5, 5], attributes={"mark": "D1"})
    assert inserted["attributes"] == {"MARK": "D1"}
    updated = backend.set_block_attributes(inserted["handle"], {"MARK": "D2"})
    assert updated["after"]["MARK"] == "D2"
    with pytest.raises(CadError):
        backend.insert_block("DOOR-TAG", [0, 0], attributes={"COLOUR": "red"})
    row = next(b for b in backend.list_blocks()["blocks"] if b["name"] == "DOOR-TAG")
    assert row["attribute_tags"] == ["MARK"]


def test_layers(backend):
    backend.create_layer("S-GRID", color_index=1)
    backend.set_layer_properties("S-GRID", on=False, locked=True, lineweight=25)
    row = next(r for r in backend.list_layers()["layers"] if r["name"] == "S-GRID")
    assert row["on"] is False and row["locked"] is True and row["lineweight"] == 25


def test_legacy_floor_plan_headless_and_saved(backend, tmp_path):
    result = backend.generate_2d_floor_plan()
    assert result["verified"] is True and result["entity_count"] == 50 and result["backend"] == "dxf"
    backend.save_drawing(str(tmp_path / "house.dxf"))
    doc = ezdxf.readfile(str(tmp_path / "house.dxf"))
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert layers == {"A-WALL-EXT", "A-WALL-INT", "A-DOOR", "A-GLAZ", "A-TEXT"}
    assert len(doc.modelspace()) == 50


def test_metric_session_units(backend):
    backend.set_drawing_units("metric_mm")
    result = backend.draw_wall([0, 0], [4000, 0])
    assert result["thickness"] == pytest.approx(230.0)
    assert backend.drawing_summary()["units"]["insunits_name"] == "mm"


def test_pin_blocks_other_documents(backend, tmp_path):
    session.pin_document(backend.active_drawing_identity())
    with pytest.raises(CadError) as info:
        backend.create_new_drawing()
    assert info.value.code == "E_DOCUMENT_PINNED"


def test_unsaved_changes_block_replacing_the_document(backend):
    backend.draw_line([0, 0], [1, 1])
    with pytest.raises(CadError) as info:
        backend.create_new_drawing()
    assert info.value.code == "E_UNSAVED_CHANGES"
    backend.close_drawing(discard_changes=True)
    assert backend.create_new_drawing()["status"] == "ok"


def test_scan_to_sqlite_uses_autocad_object_names(backend):
    backend.draw_line([0, 0], [1, 1])
    backend.draw_text("PMC-3M", [0, 0], 1)
    scan = backend.scan_all_entities()
    assert scan["entity_type_counts"] == {"AcDbLine": 1, "AcDbText": 1}
    rows = db.execute_readonly_query(scan["db_path"], "SELECT object_name FROM entities ORDER BY object_name").rows
    assert [r["object_name"] for r in rows] == ["AcDbLine", "AcDbText"]
    assert backend.count_text_patterns("PMC")["match_count"] == 1


def test_export_copy_keeps_identity(backend, tmp_path):
    backend.draw_line([0, 0], [1, 1])
    before = backend.active_drawing_identity()
    result = backend.export_dxf(str(tmp_path / "copy.dxf"))
    assert result["verified"] is True and backend.active_drawing_identity() == before


def test_render_preview_reports_missing_matplotlib(backend, tmp_path):
    if importlib.util.find_spec("matplotlib") is not None:
        pytest.skip("matplotlib is installed here; the refusal path cannot be exercised")
    with pytest.raises(CadError) as info:
        backend.render_preview(str(tmp_path / "p.png"))
    assert info.value.code == "E_DEPENDENCY_MISSING"


def test_live_only_operations_refuse_with_reason(backend):
    for call in (lambda: backend.plot_pdf("x.pdf"), lambda: backend.highlight_entity("1A"),
                 lambda: backend.launch_application()):
        with pytest.raises(CadError) as info:
            call()
        assert info.value.code == "E_UNSUPPORTED_BACKEND" and info.value.message


def test_lwpolyline_bulge_metrics():
    from backends.dxf import lwpolyline_metrics

    # A full circle of radius 1 as two half-circle bulges (bulge 1 = 180 degrees).
    length, area = lwpolyline_metrics([(1, 0, 0, 0, 1.0), (-1, 0, 0, 0, 1.0)], closed=True)
    assert length == pytest.approx(2 * math.pi)
    assert area == pytest.approx(math.pi)


def test_ensure_layer_applies_the_architectural_standard(backend):
    result = backend.ensure_layer("A-DOOR")
    assert result["color_index"] == 1  # utils.constants.ARCHITECTURAL_LAYERS
    explicit = backend.ensure_layer("A-GLAZ", color_index=30)
    assert explicit["color_index"] == 30


def test_activate_get_attributes_and_layouts_headless(backend):
    identity = backend.active_drawing_identity()
    assert backend.activate_drawing(identity)["verified"] is True
    with pytest.raises(CadError):
        backend.activate_drawing("unsaved:other.dxf")
    block = backend._doc.blocks.new("TAG")
    block.add_attdef("MARK", (0, 0), dxfattribs={"height": 1})
    handle = backend.insert_block("TAG", [0, 0], attributes={"MARK": "W1"})["handle"]
    assert backend.get_block_attributes(handle)["attributes"][0]["value"] == "W1"
    layouts = backend.list_layouts()["layouts"]
    assert layouts[0]["name"] == "Model" and layouts[0]["is_model"] is True


def test_save_back_to_own_file(backend, tmp_path):
    backend.draw_line([0, 0], [1, 1])
    backend.save_drawing(str(tmp_path / "own.dxf"))
    backend.draw_circle([0, 0], 1)
    again = backend.save_drawing()
    assert again["verified"] is True
    assert len(ezdxf.readfile(str(tmp_path / "own.dxf")).modelspace()) == 2


def test_hatch_existing_closed_boundary(backend):
    rect = backend.draw_rectangle(corner1=[0, 0], corner2=[2, 5])
    result = backend.add_hatch(boundary_handles=[rect["handle"]], pattern="SOLID")
    assert result["area"] == pytest.approx(10.0) and result["verified"] is True
    circle = backend.draw_circle([10, 10], 1)
    assert backend.add_hatch(boundary_handles=[circle["handle"]])["area"] == pytest.approx(math.pi, rel=0.01)
