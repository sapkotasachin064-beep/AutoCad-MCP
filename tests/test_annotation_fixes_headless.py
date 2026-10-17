"""Three annotation fixes through the public tool functions on the headless backend, each drawing saved to a real
DXF in tmp_path and read back with ezdxf, independently of the code under test:

* autocad_add_dimension sizes itself from a plot scale (DIMSCALE) instead of leaving the style's tiny text;
* inch and foot marks in drawn text and room labels stay inch and foot marks;
* the column grid's solid fills sit on the columns layer, never on layer 0."""

import json
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

BS = "\\"
LABEL = "LIVING 12'-6\" x 10'-0\""


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


def _on(doc, layer, kind=None):
    return [e for e in doc.modelspace() if e.dxf.layer == layer and (kind is None or e.dxftype() == kind)]


def _error(info):
    return json.loads(str(info.value))["error"]


def _rendered(dim):
    """(text heights, arrow sizes) of what ezdxf drew into the dimension's block: the sizes a reader sees."""
    parts = list(dim.virtual_entities())
    return ([v.dxf.char_height for v in parts if v.dxftype() == "MTEXT"],
            [v.dxf.xscale for v in parts if v.dxftype() == "INSERT"])


def _dimension_text(dim):
    return [v.text for v in dim.virtual_entities() if v.dxftype() == "MTEXT"]


def _drawing_file(tmp, name, **header):
    """A DXF as AutoCAD would have saved it, with these header variables, for autocad_open_drawing."""
    doc = ezdxf.new("R2018", setup=True)
    for key, value in header.items():
        doc.header[f"${key}"] = value
    path = tmp / name
    doc.saveas(str(path))
    return path


# ======= bug 1: dimensions are readable without manual DIMSCALE overrides =======


def test_a_plain_dimension_is_readable_without_touching_the_dimension_style(metric):
    result = server.autocad_add_dimension("linear", [0, 0], [4000, 0], [0, -800])
    assert result["verified"] is True and result["measurement"] == pytest.approx(4000.0)
    assert result["drawing_scale"] == 50.0 and result["drawing_scale_source"] == "default"
    assert result["dimscale"] == 50.0 and result["text_height"] == pytest.approx(150.0)
    assert result["arrow_size"] == pytest.approx(150.0) and result["drawing_unit"] == "mm"

    doc = _read(metric)
    dim = _on(doc, "0", "DIMENSION")[0]
    style = dim.override()
    assert style.get("dimscale") == 50.0 and style.get("dimtxt") == pytest.approx(3.0)
    assert style.get("dimasz") == pytest.approx(3.0) and style.get("dimlfac") == 1.0
    texts, arrows = _rendered(dim)
    assert texts == [pytest.approx(150.0)] and arrows == [pytest.approx(150.0)] * 2  # what a reader sees
    assert _dimension_text(dim) == ["4000"]
    assert doc.header["$DIMSCALE"] == 50.0  # left in the drawing: the next dimension, by hand or tool, agrees


@pytest.mark.parametrize("scale, text", [(25, 75.0), (35, 105.0), (50, 150.0), (100, 300.0), (500, 1500.0)])
def test_the_drawn_text_follows_the_drawing_scale(metric, scale, text):
    result = server.autocad_add_dimension("aligned", [0, 0], [3000, 4000], [-600, 600], drawing_scale=scale)
    assert result["drawing_scale"] == float(scale) and result["drawing_scale_source"] == "argument"
    assert result["text_height"] == pytest.approx(text) and result["measurement"] == pytest.approx(5000.0)
    dim = _on(_read(metric), "0", "DIMENSION")[0]
    assert dim.override().get("dimscale") == float(scale)
    assert _rendered(dim)[0] == [pytest.approx(text)]


def test_the_scale_is_kept_for_the_next_dimension_until_another_is_given(metric):
    server.autocad_add_dimension("linear", [0, 0], [3000, 0], [0, -600], drawing_scale=35)
    second = server.autocad_add_dimension("linear", [0, 0], [0, 2000], [-600, 0], rotation_degrees=90)
    assert second["drawing_scale"] == 35.0 and second["drawing_scale_source"] == "drawing"
    third = server.autocad_add_dimension("linear", [0, 0], [1000, 0], [0, 600], drawing_scale=100)
    assert third["drawing_scale"] == 100.0 and third["drawing_scale_source"] == "argument"
    fourth = server.autocad_add_dimension("linear", [0, 0], [1000, 0], [0, 900])
    assert fourth["drawing_scale"] == 100.0 and fourth["drawing_scale_source"] == "drawing"

    doc = _read(metric)
    assert doc.header["$DIMSCALE"] == 100.0
    scales = [d.override().get("dimscale") for d in _on(doc, "0", "DIMENSION")]
    assert sorted(scales) == [35.0, 35.0, 100.0, 100.0]


def test_a_dimscale_the_drawing_already_has_is_respected(headless):
    path = _drawing_file(headless, "scaled.dxf", INSUNITS=4, MEASUREMENT=1, LUNITS=2, LUPREC=0, DIMSCALE=25.0)
    server.autocad_open_drawing(str(path), read_only=False, pin=True)
    server.autocad_set_drawing_units("metric_mm")
    result = server.autocad_add_dimension("linear", [0, 0], [3000, 0], [0, -600])
    assert result["drawing_scale"] == 25.0 and result["drawing_scale_source"] == "drawing"
    assert result["text_height"] == pytest.approx(75.0)
    assert _rendered(_on(_read(headless), "0", "DIMENSION")[0])[0] == [pytest.approx(75.0)]


def test_an_inch_drawing_gets_inch_sized_dimensions(imperial):
    result = server.autocad_add_dimension("linear", [0, 0], [120, 0], [0, -24])
    assert result["drawing_scale"] == 50.0 and result["text_height"] == pytest.approx(6.0)
    dim = _on(_read(imperial), "0", "DIMENSION")[0]
    assert dim.override().get("dimtxt") == pytest.approx(0.12) and dim.override().get("dimdec") == 2
    assert _rendered(dim)[0] == [pytest.approx(6.0)] and _dimension_text(dim) == ["120"]


def test_a_metre_drawing_gets_metre_sized_dimensions(headless):
    server.autocad_create_new_drawing(pin=True)
    server.autocad_set_drawing_units("metric_m")
    result = server.autocad_add_dimension("linear", [0, 0], [12, 0], [0, -2])
    assert result["text_height"] == pytest.approx(0.15)
    dim = _on(_read(headless), "0", "DIMENSION")[0]
    assert _rendered(dim)[0] == [pytest.approx(0.15)] and _dimension_text(dim) == ["12"]


def test_plan_generator_dimensions_do_not_inherit_the_drawings_dimscale(metric):
    server.autocad_add_dimension("linear", [0, 0], [3000, 0], [0, -600], drawing_scale=100)
    server.autocad_draw_column_grid(x_spacings=[4000, 4000], y_spacings=[3000])
    doc = _read(metric)
    for dim in _on(doc, "COLUMNS-DIM", "DIMENSION"):
        assert dim.override().get("dimscale") == 1.0 and dim.override().get("dimtxt") == pytest.approx(150.0)
        assert _rendered(dim)[0] == [pytest.approx(150.0)]  # not 15000
    assert doc.header["$DIMSCALE"] == 100.0  # the scale the dimension tool left is still the drawing's


def test_the_dimension_tool_still_measures_and_verifies_the_geometry(metric):
    aligned = server.autocad_add_dimension("aligned", [0, 0], [3000, 4000], [-600, 600])
    linear = server.autocad_add_dimension("linear", [0, 0], [3000, 4000], [0, -500], rotation_degrees=0)
    assert aligned["measurement"] == pytest.approx(5000.0) and linear["measurement"] == pytest.approx(3000.0)
    assert aligned["state"]["verified"] is True and aligned["backend"] == "dxf"


def test_a_bad_drawing_scale_is_refused_before_anything_is_drawn(metric):
    for bad in (0, -50, 1e9, True):
        with pytest.raises(ToolError) as info:
            server.autocad_add_dimension("linear", [0, 0], [3000, 0], [0, -600], drawing_scale=bad)
        assert _error(info)["code"] == "E_INVALID_INPUT"
    assert server.autocad_drawing_summary()["model_space_entities"] == 0
    assert _read(metric).header["$DIMSCALE"] == 1.0  # and the drawing's own scale was not touched


def test_units_without_a_fixed_length_keep_the_dimension_style_and_say_so(headless):
    path = _drawing_file(headless, "unitless.dxf", INSUNITS=0)
    server.autocad_open_drawing(str(path), read_only=False, pin=True)
    server.autocad_set_drawing_units("preserve")
    result = server.autocad_add_dimension("linear", [0, 0], [3000, 0], [0, -600])
    assert result["verified"] is True and result["drawing_scale"] is None and "dimscale" not in result
    assert [n["kind"] for n in result["notices"]] == ["dimension_style_unchanged"]
    doc = _read(headless)
    assert doc.header["$DIMSCALE"] == 1.0
    assert _on(doc, "0", "DIMENSION")[0].override().dimstyle_attribs == {"dimlfac": 1.0}  # the style, as before


def test_text_override_accepts_escaped_inch_marks(metric):
    result = server.autocad_add_dimension("linear", [0, 0], [3000, 0], [0, -600], text_override=f"10{BS}'-0{BS}\" <>")
    assert result["text_override"] == "10'-0\" <>" and result["text_requested"] == f"10{BS}'-0{BS}\" <>"
    plain = server.autocad_add_dimension("linear", [0, 0], [3000, 0], [0, -900], text_override="EQ")
    assert plain["text_override"] == "EQ" and "text_requested" not in plain


# ======= bug 2: inch and foot marks in text and room labels =======


def test_inch_and_foot_marks_are_drawn_as_typed(metric):
    single = server.autocad_draw_text(LABEL, [0, 0], 150)
    multi = server.autocad_draw_mtext(f"LIVING{BS}P{LABEL}", [0, 500], 150)
    assert single["text"] == LABEL and multi["text"] == f"LIVING{BS}P{LABEL}"
    assert "text_requested" not in single and "text_requested" not in multi

    doc = _read(metric)
    assert [e.dxf.text for e in _on(doc, "0", "TEXT")] == [LABEL]
    assert [e.text for e in _on(doc, "0", "MTEXT")] == [f"LIVING{BS}P{LABEL}"]
    assert LABEL in (metric / "out.dxf").read_text(encoding="utf-8")


def test_a_backslash_in_front_of_an_inch_or_foot_mark_is_not_drawn(metric):
    sent = f"LIVING 12{BS}'-6{BS}\" x 10{BS}'-0{BS}\""
    single = server.autocad_draw_text(sent, [0, 0], 150)
    multi = server.autocad_draw_mtext(f"LIVING{BS}P{sent}", [0, 500], 150)
    assert single["text"] == LABEL and single["text_requested"] == sent
    assert multi["text"] == f"LIVING{BS}P{LABEL}" and multi["text_requested"] == f"LIVING{BS}P{sent}"

    doc = _read(metric)
    assert [e.dxf.text for e in _on(doc, "0", "TEXT")] == [LABEL]
    assert [e.text for e in _on(doc, "0", "MTEXT")] == [f"LIVING{BS}P{LABEL}"]
    raw = (metric / "out.dxf").read_text(encoding="utf-8")
    assert f"{BS}\"" not in raw and f"{BS}'" not in raw


def test_mtext_codes_and_literal_backslashes_survive_the_cleaning(metric):
    sent = f"C:{BS}{BS}plans{BS}PFLOOR {BS}Fsimplex;1{BS}S1/2;"
    result = server.autocad_draw_mtext(sent, [0, 0], 150)
    assert result["text"] == sent and "text_requested" not in result
    assert [e.text for e in _on(_read(metric), "0", "MTEXT")] == [sent]


def test_real_line_breaks_in_mtext_become_paragraph_breaks(metric):
    result = server.autocad_draw_mtext(f"LIVING\n{LABEL}\r\nSOUTH", [0, 0], 150)
    assert result["text"] == f"LIVING{BS}P{LABEL}{BS}PSOUTH" and result["text_requested"].count("\n") == 2
    assert [e.text for e in _on(_read(metric), "0", "MTEXT")] == [f"LIVING{BS}P{LABEL}{BS}PSOUTH"]


def test_room_labels_keep_their_inch_marks(metric):
    rooms = [{"name": f"Bed 12{BS}'x10{BS}\"", "x": 0, "y": 0, "width": 5, "depth": 4},
             {"name": "Kitchen", "x": 5, "y": 0, "width": 3, "depth": 4}]
    result = server.autocad_generate_floor_plan(rooms=rooms, unit="m", windows="none", dimensions=False)
    assert [r["name"] for r in result["rooms"]] == ["Bed 12'x10\"", "Kitchen"]
    labels = sorted(e.text for e in _on(_read(metric), "A-TEXT", "MTEXT"))
    assert labels[0].startswith("Bed 12'x10\"" + BS + "P") and labels[1].startswith("Kitchen" + BS + "P")
    assert all(f"{BS}\"" not in text and f"{BS}'" not in text for text in labels)


def test_legacy_floor_plan_room_names_keep_their_inch_marks(imperial):
    rooms = [{"name": f"Living 20{BS}'x14{BS}\"", "col": 0, "row": 0, "col_span": 2, "row_span": 1},
             {"name": "Kitchen", "col": 0, "row": 1}, {"name": "Bath", "col": 1, "row": 1},
             {"name": "Bedroom 1", "col": 0, "row": 2}, {"name": "Bedroom 2", "col": 1, "row": 2}]
    server.autocad_generate_2d_floor_plan(rooms_config=rooms)
    labels = [e.text for e in _on(_read(imperial), "A-TEXT", "MTEXT")]
    assert "Living 20'x14\"" in labels and all(BS not in text for text in labels)


def test_title_block_fields_keep_their_inch_marks_and_line_breaks(metric):
    server.autocad_draw_sheet(paper="A3", scale=50, fields={"title": f"GROUND FLOOR\n12{BS}'-6{BS}\" BAY",
                                                              "project": "House 2\""})
    texts = {e.text for e in _on(_read(metric), "G-ANNO-TTLB-TEXT", "MTEXT")}
    assert f"GROUND FLOOR{BS}P12'-6\" BAY" in texts and "House 2\"" in texts


# ======= bug 3: column fills sit on the columns layer =======


def test_every_column_hatch_is_on_the_columns_layer_and_none_on_layer_0(metric):
    server.autocad_draw_column_grid(x_spacings=[4000, 4000], y_spacings=[3000])
    doc = _read(metric)
    hatches = [e for e in doc.modelspace() if e.dxftype() == "HATCH"]
    assert len(hatches) == 6 and {h.dxf.layer for h in hatches} == {"COLUMNS"}
    assert all(h.dxf.pattern_name == "SOLID" and h.dxf.solid_fill == 1 for h in hatches)
    assert Counter(e.dxf.layer for e in doc.modelspace()) == {"COLUMNS": 12, "COLUMNS-TEXT": 6, "COLUMNS-DIM": 4}
    assert _on(doc, "0") == []  # nothing, hatch or otherwise, landed on layer 0
    outlines = _on(doc, "COLUMNS", "LWPOLYLINE")
    assert len(outlines) == len(hatches)  # one outline per fill, on the same layer


def test_a_custom_column_layer_gets_its_hatches_too(metric):
    server.autocad_draw_column_grid(points=[[0, 0], [4000, 0]], layer="S-COL", dimensions=False)
    doc = _read(metric)
    assert {e.dxf.layer for e in doc.modelspace() if e.dxftype() == "HATCH"} == {"S-COL"}
    assert _on(doc, "0") == [] and _on(doc, "COLUMNS") == []


def test_structural_grid_column_fills_are_on_their_own_layer(metric):
    server.autocad_draw_structural_grid(x_spacings=[4.0], y_spacings=[3.0], unit="m", column_size=[0.3, 0.3])
    doc = _read(metric)
    hatches = [e for e in doc.modelspace() if e.dxftype() == "HATCH"]
    assert hatches and {h.dxf.layer for h in hatches} == {"S-COLS"}
    assert _on(doc, "0") == []
