"""Behaviour of the V0.3.0 COM tool modules against tests/fakes.py.

These prove call sequences, validation order, verification logic and result
shapes. They are NOT evidence of AutoCAD's behaviour: every tool exercised
here is reported as "mock-tested, not live-verified" until
test_integration_autocad.py runs it against a real AutoCAD.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cad_engine
from core import session
from core.errors import CadError
from fakes import FakeApp, FakeBlock
from tools import annotation, blocks, documents, editing, layers, modify, output, primitives, query

MODULES = ("documents", "query", "modify", "annotation", "blocks", "output", "layers", "primitives", "editing")


@pytest.fixture
def app(monkeypatch, tmp_path):
    fake = FakeApp()
    for module in MODULES:
        monkeypatch.setattr(f"tools.{module}.get_connected_app", lambda: fake)
    monkeypatch.setenv("AUTOCAD_MCP_OUTPUT_DIR", str(tmp_path))
    monkeypatch.delenv("AUTOCAD_MCP_UNITS", raising=False)
    session.unpin_document()
    session.set_units_override(None)
    yield fake
    session.unpin_document()
    session.set_units_override(None)


def _doc(app):
    return app.ActiveDocument


# ======= documents =======


def test_list_drawings_reports_the_active_one(app):
    result = documents.list_drawings()
    assert result["count"] == 1
    assert result["drawings"][0]["active"] is True
    assert result["drawings"][0]["identity"] == "unsaved:drawing1.dwg"


def test_open_drawing_read_only_by_default(app, tmp_path):
    path = tmp_path / "site.dwg"
    path.write_bytes(b"AC1032")
    result = documents.open_drawing(str(path))
    assert result["read_only"] is True
    assert result["drawing_identity"] == f"path:{str(path.resolve()).lower()}"
    assert result["verified"] is True


def test_open_drawing_refuses_while_pinned(app, tmp_path):
    path = tmp_path / "site.dwg"
    path.write_bytes(b"AC1032")
    session.pin_document("unsaved:drawing1.dwg")
    with pytest.raises(CadError) as info:
        documents.open_drawing(str(path))
    assert info.value.code == "E_DOCUMENT_PINNED"
    assert len(app._docs) == 1  # nothing opened


def test_open_drawing_rejects_unknown_extension_before_com(app, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("x")
    with pytest.raises(CadError) as info:
        documents.open_drawing(str(path))
    assert info.value.code == "E_INVALID_INPUT"


def test_save_as_writes_file_reports_evidence_and_moves_pin(app, tmp_path):
    session.pin_document("unsaved:drawing1.dwg")
    target = tmp_path / "plan.dwg"
    result = documents.save_drawing(str(target))
    assert result["saved"] is True and result["verified"] is True
    assert result["file"]["size_bytes"] > 0 and len(result["file"]["sha256"]) == 64
    assert result["pin_moved"] == {"from": "unsaved:drawing1.dwg", "to": f"path:{str(target.resolve()).lower()}"}
    assert session.pinned_document() == result["drawing_identity"]
    assert _doc(app).saves[-1][2] == 64  # AcSaveAsType ac2018_dwg


def test_save_refuses_to_replace_another_file(app, tmp_path):
    target = tmp_path / "existing.dwg"
    target.write_bytes(b"precious")
    with pytest.raises(CadError) as info:
        documents.save_drawing(str(target))
    assert info.value.code == "E_OUTPUT_EXISTS"
    assert target.read_bytes() == b"precious"


def test_save_without_path_needs_a_previous_save(app):
    with pytest.raises(CadError) as info:
        documents.save_drawing()
    assert info.value.code == "E_INVALID_INPUT"


def test_close_refuses_unsaved_changes(app):
    primitives.draw_line([0, 0], [1, 1])
    with pytest.raises(CadError) as info:
        documents.close_drawing()
    assert info.value.code == "E_UNSAVED_CHANGES"
    assert len(app._docs) == 1
    result = documents.close_drawing(discard_changes=True)
    assert result["verified"] is True and result["discarded_changes"] is True
    assert app._docs == []


def test_set_drawing_units_sticks_for_the_session(app):
    result = documents.set_drawing_units("metric_mm")
    assert result["changed"]["INSUNITS"] == {"from": 1, "to": 4}
    # A later drawing tool must not flip the drawing back to the env default.
    primitives.draw_line([0, 0], [1000, 0])
    assert _doc(app).vars["INSUNITS"] == 4


# ======= query =======


def _populate(app):
    primitives.draw_line([0, 0], [10, 0], layer="A-WALL")
    primitives.draw_circle([5, 5], 2)
    primitives.draw_text("ROOM", [1, 1], 2.5, layer="A-TEXT")
    return _doc(app)


def test_drawing_summary_counts_by_type_and_layer(app):
    _populate(app)
    result = query.drawing_summary()
    assert result["counts_by_type"] == {"LINE": 1, "CIRCLE": 1, "TEXT": 1}
    assert result["counts_by_layer"]["A-WALL"] == 1
    assert result["units"]["insunits_name"] == "in"
    assert result["truncated"] is False


def test_list_entities_filters_and_pages(app):
    _populate(app)
    lines = query.list_entities(entity_types=["line"])
    assert [e["type"] for e in lines["entities"]] == ["LINE"]
    first = query.list_entities(limit=2)
    assert first["returned"] == 2 and first["truncated"] is True and first["next_offset"] == 2
    rest = query.list_entities(offset=2, limit=2)
    assert rest["returned"] == 1 and rest["truncated"] is False
    on_layer = query.list_entities(layers=["a-text"])
    assert on_layer["total"] == 1


def test_list_entities_rejects_unknown_type(app):
    with pytest.raises(CadError) as info:
        query.list_entities(entity_types=["WALL"])
    assert info.value.code == "E_INVALID_INPUT"


def test_get_entity_reports_line_geometry(app):
    handle = primitives.draw_line([0, 0], [3, 4])["handle"]
    entity = query.get_entity(handle)["entity"]
    assert entity["type"] == "LINE" and entity["length"] == pytest.approx(5.0)


def test_read_only_queries_never_change_units(app):
    _doc(app).vars.update(INSUNITS=4, LUNITS=2, MEASUREMENT=1)
    query.drawing_summary()
    query.list_entities()
    assert _doc(app).vars["INSUNITS"] == 4


# ======= modify =======


def test_scale_verifies_extents(app):
    handle = primitives.draw_line([0, 0], [10, 0])["handle"]
    result = modify.scale_entity(handle, [0, 0], 2.0)
    assert result["verification"] == "extents_scaled_by_factor"


def test_mirror_offset_array(app):
    handle = primitives.draw_line([0, 0], [10, 0])["handle"]
    assert modify.mirror_entity(handle, [0, 5], [10, 5])["new_handle"] != handle
    assert len(modify.offset_entity(handle, 2.0)["new_handles"]) == 1
    result = modify.array_rectangular(handle, 2, 3, 10.0, 20.0)
    assert len(result["new_handles"]) == 5


def test_delete_is_a_dry_run_by_default(app):
    handle = primitives.draw_line([0, 0], [1, 1])["handle"]
    plan = modify.delete_entities([handle])
    assert plan["dry_run"] is True and plan["would_delete"][0]["handle"] == handle
    assert _doc(app).ModelSpace.Count == 1
    done = modify.delete_entities([handle, "FFFF"], dry_run=False)
    assert done["verified"] is True and done["not_found"] == ["FFFF"]
    assert _doc(app).ModelSpace.Count == 0


def test_set_entity_properties_creates_layer_and_reads_back(app):
    handle = primitives.draw_line([0, 0], [1, 1])["handle"]
    result = modify.set_entity_properties([handle], layer="S-COLS", color_index=256, lineweight=35)
    assert result["verified"] is True
    assert _doc(app).Layers.Item("S-COLS").Name == "S-COLS"


def test_set_layer_properties_loads_linetype(app):
    layers.create_layer("A-HIDDEN")
    result = layers.set_layer_properties("A-HIDDEN", linetype="hidden", lineweight=25, locked=True)
    assert result["verified"] is True
    assert result["after"]["Linetype"] == "HIDDEN"


def test_cannot_freeze_current_layer(app):
    with pytest.raises(CadError):
        layers.set_layer_properties("0", frozen=True)


# ======= annotation =======


def test_arc_and_mtext(app):
    arc = annotation.draw_arc([0, 0], 5, 0, 90)
    assert arc["end_angle_degrees"] == pytest.approx(90)
    mtext = annotation.draw_mtext("Kitchen\\P12 m2", [0, 0], 3.0, width=40)
    assert mtext["height"] == 3.0


def test_dimensions_measure_the_geometry(app):
    aligned = annotation.add_dimension("aligned", [0, 0], [3, 4], [0, 10])
    assert aligned["measurement"] == pytest.approx(5.0)
    linear = annotation.add_dimension("linear", [0, 0], [3, 4], [0, 10], rotation_degrees=0)
    assert linear["measurement"] == pytest.approx(3.0)


def test_hatch_from_points_reads_pattern_back(app):
    result = annotation.add_hatch(boundary_points=[[0, 0], [4, 0], [4, 3], [0, 3]], pattern="ansi31")
    assert result["pattern"] == "ANSI31"
    assert result["area"] == pytest.approx(12.0)
    assert result["boundary_handle"]


def test_hatch_needs_exactly_one_boundary(app):
    with pytest.raises(CadError):
        annotation.add_hatch()


# ======= blocks =======


def test_insert_block_with_attributes(app):
    _doc(app).Blocks._items["DOOR-TAG"] = FakeBlock("DOOR-TAG", attdefs=("MARK", "WIDTH"))
    result = blocks.insert_block("DOOR-TAG", [5, 5], attributes={"mark": "D1", "WIDTH": "900"})
    assert result["attributes"] == {"MARK": "D1", "WIDTH": "900"}
    updated = blocks.set_block_attributes(result["handle"], {"WIDTH": "750"})
    assert updated["after"]["WIDTH"] == "750" and updated["verified"] is True
    listed = blocks.list_blocks()
    assert listed["blocks"][0]["attribute_tags"] == ["MARK", "WIDTH"]


def test_insert_block_rejects_unknown_tag_before_inserting(app):
    _doc(app).Blocks._items["DOOR-TAG"] = FakeBlock("DOOR-TAG", attdefs=("MARK",))
    with pytest.raises(CadError):
        blocks.insert_block("DOOR-TAG", [0, 0], attributes={"COLOUR": "red"})
    assert _doc(app).ModelSpace.Count == 0


def test_insert_missing_block(app):
    with pytest.raises(CadError) as info:
        blocks.insert_block("NOPE", [0, 0])
    assert info.value.code == "E_BLOCK_NOT_FOUND"


# ======= output =======


def test_export_dxf_leaves_document_identity_alone(app, tmp_path):
    target = tmp_path / "copy.dxf"
    result = output.export_dxf(str(target))
    assert result["verified"] is True and result["document_unchanged"] is True
    assert target.exists()
    assert not list(tmp_path.glob(".copy.*"))  # temp file cleaned up
    with pytest.raises(CadError) as info:
        output.export_dxf(str(target))
    assert info.value.code == "E_OUTPUT_EXISTS"


def test_plot_pdf_forces_foreground_and_restores_settings(app, tmp_path):
    doc = _doc(app)
    target = tmp_path / "sheet.pdf"
    result = output.plot_pdf(str(target), paper="ISO_full_bleed_A3")
    assert result["verified"] is True and result["paper_mm"] == [420.0, 297.0]
    assert doc.Plot.calls[0][2] == 0  # BACKGROUNDPLOT was 0 while plotting
    assert doc.vars["BACKGROUNDPLOT"] == 2  # and restored afterwards
    assert doc.ModelSpace.Layout.ConfigName == "None"  # layout settings restored
    assert result["layout_settings_restored"] is True


def test_plot_leaves_empty_media_at_device_default(app, tmp_path):
    # Live AutoCAD 2024: a fresh model layout reports CanonicalMediaName '' and
    # rejects '' as input, so it must not be written back or counted as a failure.
    layout = _doc(app).ModelSpace.Layout
    layout.CanonicalMediaName = ""
    result = output.plot_pdf(str(tmp_path / "sheet.pdf"), paper="ISO_full_bleed_A3")
    assert result["layout_settings_restored"] is True
    assert result["layout_settings_not_restored"] == {}
    assert result["layout_settings_left_at_device_default"] == ["CanonicalMediaName"]
    assert layout.ConfigName == "None"


def test_plot_unknown_layout(app, tmp_path):
    with pytest.raises(CadError) as info:
        output.plot_pdf(str(tmp_path / "x.pdf"), layout="A1-Sheet")
    assert info.value.code == "E_LAYOUT_NOT_FOUND"


def test_ambiguous_paper_is_rejected_with_candidates(app, tmp_path):
    with pytest.raises(CadError) as info:
        output.plot_pdf(str(tmp_path / "x.pdf"), paper="ISO")
    assert info.value.details["candidates"]


# ======= legacy tools on the fake, with notices =======


def test_move_verified_by_bounding_box(app):
    handle = primitives.draw_line([0, 0], [10, 0])["handle"]
    result = editing.move_entity(handle, [5, 5, 0])
    assert result["verification"] == "bounding_box_shifted_by_displacement"


def test_notices_report_units_applied_on_write(app):
    _doc(app).vars.update(INSUNITS=4, LUNITS=2, MEASUREMENT=1, LUPREC=0)
    result, notices = session.collect(lambda: primitives.draw_line([0, 0], [1, 1]))
    assert notices[0]["kind"] == "units_changed"
    assert cad_engine.read_insunits(_doc(app)) == 1


# ======= gaps closed for the capability catalog =======


def test_activate_drawing_switches_and_respects_pin(app):
    first = _doc(app)
    second = app.Documents.Add()
    assert _doc(app) is second
    result = documents.activate_drawing("unsaved:drawing1.dwg")
    assert result["verified"] is True and _doc(app) is first
    session.pin_document("unsaved:drawing1.dwg")
    with pytest.raises(CadError) as info:
        documents.activate_drawing("unsaved:drawing2.dwg")
    assert info.value.code == "E_DOCUMENT_PINNED"
    with pytest.raises(CadError) as info:
        documents.activate_drawing("unsaved:nope.dwg", pin=True)
    assert info.value.code == "E_DOCUMENT_NOT_FOUND"


def test_highlight_temporary_is_read_only_and_persistent_reads_back(app):
    _doc(app).vars.update(INSUNITS=4, LUNITS=2, MEASUREMENT=1, LUPREC=0)
    handle = primitives.draw_line([0, 0], [1, 1])["handle"]  # write: applies units once
    _doc(app).vars.update(INSUNITS=4)  # pretend the user switched units back
    temp = editing.highlight_entity(handle)
    assert temp["highlighted"] is True and _doc(app).vars["INSUNITS"] == 4  # temporary = read-only
    persistent = editing.highlight_entity(handle, method="persistent", color=4)
    assert persistent["verified"] is True and persistent["color"] == 4
    primitives.draw_text("PMC-3M", [0, 0], 1)
    matches = editing.highlight_text_matches("PMC", limit=1)
    assert matches["match_count"] == 1 and matches["truncated"] is False


def test_get_block_attributes_lists_tags(app):
    _doc(app).Blocks._items["TAG"] = FakeBlock("TAG", attdefs=("MARK",))
    handle = blocks.insert_block("TAG", [0, 0], attributes={"MARK": "W1"})["handle"]
    rows = blocks.get_block_attributes(handle)["attributes"]
    assert [(r["tag"], r["value"]) for r in rows] == [("MARK", "W1")]


def test_list_layouts_marks_model_and_current(app):
    result = output.list_layouts()
    names = {lo["name"]: lo for lo in result["layouts"]}
    assert names["Model"]["is_model"] is True and names["Model"]["current"] is True
    assert "Layout1" in names


def test_save_back_to_own_file_after_save_as(app, tmp_path):
    target = tmp_path / "own.dwg"
    documents.save_drawing(str(target))
    primitives.draw_line([0, 0], [1, 1])  # makes the drawing dirty again
    again = documents.save_drawing()  # plain Save to its own file
    assert again["verified"] is True and again["file"]["path"] == str(target.resolve())
    assert _doc(app).saves[-1][0] == "Save"
    # Saving to its own path through path= needs no overwrite flag either.
    assert documents.save_drawing(str(target))["saved"] is True


def test_open_already_open_drawing_activates_it(app, tmp_path):
    path = tmp_path / "site.dwg"
    path.write_bytes(b"AC1032")
    documents.open_drawing(str(path))
    app.Documents.Add()  # another drawing becomes active
    result = documents.open_drawing(str(path))
    assert result["already_open"] is True and len(app._docs) == 3


def test_hatch_existing_closed_boundary(app):
    rect = primitives.draw_rectangle(corner1=[0, 0], corner2=[2, 5])  # closed AcDb3dPolyline
    result = annotation.add_hatch(boundary_handles=[rect["handle"]], pattern="SOLID")
    assert result["pattern"] == "SOLID" and result["area"] == pytest.approx(10.0)
