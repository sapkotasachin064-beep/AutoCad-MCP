"""The three annotation fixes drawn through the COM tool modules into tests/fakes.py, the recorded fake of
AutoCAD's object model: dimensions sized from a plot scale (DIMSCALE), inch and foot marks in drawn text, and
entities created on their own layer.

These prove which COM calls this code makes, in what order, and what it reads back -- not AutoCAD's behaviour.
Nothing here is evidence that a live AutoCAD accepts ScaleFactor on a dimension or CLAYER from SetVariable."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import session  # noqa: E402
from core.errors import CadError, VerificationError  # noqa: E402
from domain import macros, units  # noqa: E402
from fakes import FakeApp, FakeEntity, FakeSpace, com_error  # noqa: E402
from tools import annotation, architectural, drawing  # noqa: E402

BS = "\\"
LABEL = "LIVING 12'-6\" x 10'-0\""


@pytest.fixture
def app(monkeypatch):
    fake = FakeApp()
    for module in ("annotation", "architectural", "drawing"):
        monkeypatch.setattr(f"tools.{module}.get_connected_app", lambda: fake)
    monkeypatch.delenv("AUTOCAD_MCP_UNITS", raising=False)
    session.unpin_document()
    session.set_units_override(None)
    yield fake
    session.unpin_document()
    session.set_units_override(None)


@pytest.fixture
def metric_app(app, monkeypatch):
    monkeypatch.setenv("AUTOCAD_MCP_UNITS", "metric_mm")
    return app


def _doc(app):
    return app.ActiveDocument


def _items(app):
    return _doc(app).ModelSpace._items


def _on(app, layer, object_name=None):
    return [e for e in _items(app) if e.Layer == layer and (object_name is None or e.ObjectName == object_name)]


def _draw(build):
    plan, handles, identity, code = architectural.run_plan_com(build, dry_run=False)
    return plan, handles


def _columns(c, **kwargs):
    return macros.plan_column_grid(c, x_spacings=[4000, 4000], y_spacings=[3000], **kwargs)


class StubbornHatch(FakeEntity):
    """A hatch AutoCAD keeps on the layer it was created on: a Layer assigned afterwards does not stick."""

    def __setattr__(self, name, value):
        if name == "Layer" and getattr(self, "_born", False):
            return
        super().__setattr__(name, value)


@pytest.fixture
def stubborn_hatches(monkeypatch):
    original = FakeSpace.AddHatch

    def add_hatch(space, *args):
        hatch = original(space, *args)
        hatch.__class__ = StubbornHatch
        hatch._born = True
        return hatch

    monkeypatch.setattr(FakeSpace, "AddHatch", add_hatch)


# ======= bug 3: entities are created on their own layer =======


def test_column_hatches_are_created_on_the_columns_layer_not_moved_there_afterwards(metric_app, stubborn_hatches):
    _draw(_columns)
    assert len(_on(metric_app, "COLUMNS", "AcDbHatch")) == 6
    assert _on(metric_app, "0") == []  # not a hatch, not a boundary polyline left on layer 0
    assert len(_on(metric_app, "COLUMNS", "AcDbPolyline")) == 6
    assert _doc(metric_app).vars["CLAYER"] == "0"  # the drawing's own current layer is put back


def test_every_layer_of_a_plan_is_drawn_on_directly_and_the_current_layer_is_restored(metric_app):
    doc = _doc(metric_app)
    doc.Layers.Add("A-WALL")
    doc.SetVariable("CLAYER", "A-WALL")  # whatever layer the user was working on
    switched = []
    original = doc.SetVariable
    doc.SetVariable = lambda name, value: (switched.append(value) if name == "CLAYER" else None, original(name, value))[1]
    _draw(_columns)
    assert doc.vars["CLAYER"] == "A-WALL"
    assert switched[0] == "COLUMNS" and switched[-1] == "A-WALL"
    assert {"COLUMNS", "COLUMNS-TEXT", "COLUMNS-DIM"} <= set(switched)
    assert _on(metric_app, "A-WALL") == []  # the working layer received nothing from the plan


def test_the_layer_is_only_switched_when_the_next_primitive_needs_another(metric_app):
    doc = _doc(metric_app)
    switched = []
    original = doc.SetVariable
    doc.SetVariable = lambda name, value: (switched.append(value) if name == "CLAYER" else None, original(name, value))[1]
    plan, _ = _draw(lambda c: macros.plan_column_grid(c, points=[[0, 0]], labels=False, dimensions=False))
    assert [p.layer for p in plan.primitives] == ["COLUMNS", "COLUMNS"]  # outline, fill
    assert switched == ["COLUMNS", "0"]  # in, and back out once


def test_a_layer_autocad_will_not_make_current_gets_its_entities_moved_onto_it_with_a_notice(metric_app):
    layer = _doc(metric_app).Layers.Add("COLUMNS")
    layer.Freeze = True  # AutoCAD cannot make a frozen layer current
    (plan, handles), notices = session.collect(lambda: _draw(
        lambda c: macros.plan_column_grid(c, x_spacings=[4000], y_spacings=[3000], labels=False, dimensions=False)))
    assert len(handles) == 8 and len(_on(metric_app, "COLUMNS")) == 8 and _on(metric_app, "0") == []
    refused = [n for n in notices if n["kind"] == "layer_not_made_current"]
    assert len(refused) == 1 and refused[0]["layer"] == "COLUMNS"  # said once, not once per entity
    assert _doc(metric_app).vars["CLAYER"] == "0"


def test_an_entity_autocad_leaves_on_another_layer_is_an_error_not_a_quiet_wrong_layer(metric_app, stubborn_hatches):
    _doc(metric_app).Layers.Add("COLUMNS").Freeze = True
    with pytest.raises(VerificationError, match="'COLUMNS'") as info:
        _draw(_columns)
    assert info.value.details["expected_layer"] == "COLUMNS" and info.value.details["layer_read_back"] == "0"
    assert _doc(metric_app).vars["CLAYER"] == "0"  # restored even though drawing stopped half-way


def test_a_current_layer_that_cannot_be_read_is_never_changed(metric_app):
    doc = _doc(metric_app)
    original_get, original_set = doc.GetVariable, doc.SetVariable
    changed = []

    def get(name):
        if name == "CLAYER":
            raise com_error("Unavailable")
        return original_get(name)

    def set_(name, value):
        if name == "CLAYER":
            changed.append(value)
        return original_set(name, value)

    doc.GetVariable, doc.SetVariable = get, set_
    _draw(lambda c: macros.plan_column_grid(c, points=[[0, 0]], labels=False, dimensions=False))
    assert changed == []  # it could not be put back, so it was not touched
    assert {e.Layer for e in _items(metric_app)} == {"COLUMNS"}  # the entities were still moved onto their layer


def test_layer_names_are_compared_the_way_autocad_does_not_by_case(metric_app):
    _doc(metric_app).Layers.Add("Columns")  # exists already with this spelling
    _draw(lambda c: macros.plan_column_grid(c, points=[[0, 0]], labels=False, dimensions=False))
    assert {e.Layer for e in _items(metric_app)} == {"Columns"}


# ======= bug 1: dimensions sized from a plot scale =======


def _only_dimension(app):
    dims = [e for e in _items(app) if "Dimension" in e.ObjectName]
    assert len(dims) == 1
    return dims[0]


def test_the_dimension_tool_sizes_a_metric_dimension_for_a_1_to_50_plot(metric_app):
    result = annotation.add_dimension("linear", [0, 0], [4000, 0], [0, -800])
    dim = _only_dimension(metric_app)
    assert dim.ScaleFactor == 50.0 and dim.TextHeight == pytest.approx(3.0) and dim.ArrowheadSize == pytest.approx(3.0)
    assert dim.ExtensionLineExtend == pytest.approx(1.5) and dim.ExtensionLineOffset == pytest.approx(0.75)
    assert dim.TextGap == pytest.approx(0.75) and dim.PrimaryUnitsPrecision == 0
    assert _doc(metric_app).vars["DIMSCALE"] == 50.0  # the drawing carries it for the next dimension
    assert result["drawing_scale"] == 50.0 and result["drawing_scale_source"] == "default"
    assert result["text_height"] == pytest.approx(150.0) and result["arrow_size"] == pytest.approx(150.0)
    assert result["scale_confirmed"] is True and result["read_back"] == {"dimscale": 50.0, "text_height": 3.0}
    assert result["measurement"] == pytest.approx(4000.0) and result["verified"] is True
    assert result["drawing_unit"] == "mm"  # the unit the sizes were worked out in


def test_an_inch_drawing_gets_inch_sized_text_at_the_same_scale(app):
    result = annotation.add_dimension("aligned", [0, 0], [30, 40], [-6, 6])
    dim = _only_dimension(app)
    assert dim.ScaleFactor == 50.0 and dim.TextHeight == pytest.approx(0.12) and dim.PrimaryUnitsPrecision == 2
    assert result["text_height"] == pytest.approx(6.0) and result["measurement"] == pytest.approx(50.0)


def test_the_scale_asked_for_is_used_and_kept(metric_app):
    first = annotation.add_dimension("linear", [0, 0], [3000, 0], [0, -600], drawing_scale=35)
    second = annotation.add_dimension("linear", [0, 0], [2000, 0], [0, -900])
    dims = [e for e in _items(metric_app) if "Dimension" in e.ObjectName]
    assert [d.ScaleFactor for d in dims] == [35.0, 35.0] and all(d.TextHeight == pytest.approx(3.0) for d in dims)
    assert first["drawing_scale_source"] == "argument" and first["text_height"] == pytest.approx(105.0)
    assert second["drawing_scale_source"] == "drawing" and second["drawing_scale"] == 35.0
    assert _doc(metric_app).vars["DIMSCALE"] == 35.0


def test_a_dimscale_the_drawing_already_has_is_respected(metric_app):
    _doc(metric_app).vars["DIMSCALE"] = 100.0  # set by hand in AutoCAD
    result = annotation.add_dimension("linear", [0, 0], [3000, 0], [0, -600])
    assert result["drawing_scale"] == 100.0 and result["drawing_scale_source"] == "drawing"
    assert _only_dimension(metric_app).ScaleFactor == 100.0 and result["text_height"] == pytest.approx(300.0)


def test_the_dimension_is_created_while_the_drawing_has_the_new_scale(metric_app, monkeypatch):
    """DIMSCALE is set before AddDimRotated, so even a dimension whose ScaleFactor AutoCAD refuses gets it."""

    class NoScaleFactor(FakeEntity):
        def __setattr__(self, name, value):
            if name == "ScaleFactor" and getattr(self, "_born", False):
                raise com_error("Invalid input")
            super().__setattr__(name, value)

    space = _doc(metric_app).ModelSpace
    original = space.AddDimRotated

    def add(*args):
        entity = original(*args)
        entity.__class__ = NoScaleFactor
        entity._born = True
        return entity

    monkeypatch.setattr(space, "AddDimRotated", add)
    result, notices = session.collect(lambda: annotation.add_dimension("linear", [0, 0], [3000, 0], [0, -600],
                                                                       drawing_scale=35))
    assert _only_dimension(metric_app).ScaleFactor == 35.0  # taken from the drawing's DIMSCALE at creation
    assert [n["property"] for n in notices if n["kind"] == "dimension_size_not_applied"] == ["ScaleFactor"]
    assert result["scale_confirmed"] is True


def test_a_size_autocad_does_not_confirm_is_reported_not_hidden(metric_app, monkeypatch):
    class NoTextHeight(FakeEntity):
        def __setattr__(self, name, value):
            if name == "TextHeight":
                raise com_error("Invalid input")
            super().__setattr__(name, value)

    space = _doc(metric_app).ModelSpace
    original = space.AddDimRotated

    def add(*args):
        entity = original(*args)
        entity.__class__ = NoTextHeight
        return entity

    monkeypatch.setattr(space, "AddDimRotated", add)
    result, notices = session.collect(lambda: annotation.add_dimension("linear", [0, 0], [3000, 0], [0, -600]))
    kinds = [n["kind"] for n in notices]
    assert "dimension_size_not_applied" in kinds and "dimension_scale_not_confirmed" in kinds
    assert result["scale_confirmed"] is False and result["verified"] is True  # the dimension itself is fine


def test_units_without_a_fixed_length_keep_the_dimension_style(app, monkeypatch):
    monkeypatch.setenv("AUTOCAD_MCP_UNITS", "preserve")
    _doc(app).vars["INSUNITS"] = 0
    result, notices = session.collect(lambda: annotation.add_dimension("linear", [0, 0], [30, 0], [0, -6]))
    dim = _only_dimension(app)
    assert not hasattr(dim, "TextHeight") and _doc(app).vars["DIMSCALE"] == 1.0
    assert result["drawing_scale"] is None and [n["kind"] for n in notices] == ["dimension_style_unchanged"]


def test_a_bad_drawing_scale_is_refused_before_anything_is_drawn(metric_app):
    for bad in (0, -5, True, 10 ** 9):
        with pytest.raises(CadError) as info:
            annotation.add_dimension("linear", [0, 0], [3000, 0], [0, -600], drawing_scale=bad)
        assert info.value.code == "E_INVALID_INPUT"
    assert _doc(metric_app).ModelSpace.Count == 0 and _doc(metric_app).vars["DIMSCALE"] == 1.0


def test_plan_generator_dimensions_keep_their_absolute_sizes_whatever_the_drawing_dimscale(metric_app):
    _doc(metric_app).vars["DIMSCALE"] = 100.0
    _draw(_columns)
    dims = [e for e in _items(metric_app) if "Dimension" in e.ObjectName]
    assert len(dims) == 4
    assert all(d.ScaleFactor == 1.0 and d.TextHeight == pytest.approx(150.0) for d in dims)
    assert _doc(metric_app).vars["DIMSCALE"] == 100.0  # the drawing's own scale is put back


def test_plan_generator_dimensions_do_not_inherit_the_scale_even_if_scalefactor_is_refused(metric_app, monkeypatch):
    class NoScaleFactor(FakeEntity):
        def __setattr__(self, name, value):
            if name == "ScaleFactor" and getattr(self, "_born", False):
                raise com_error("Invalid input")
            super().__setattr__(name, value)

    space = _doc(metric_app).ModelSpace
    original = space.AddDimRotated

    def add(*args):
        entity = original(*args)
        entity.__class__ = NoScaleFactor
        entity._born = True
        return entity

    monkeypatch.setattr(space, "AddDimRotated", add)
    _doc(metric_app).vars["DIMSCALE"] = 100.0
    _draw(_columns)
    dims = [e for e in _items(metric_app) if "Dimension" in e.ObjectName]
    assert dims and all(d.ScaleFactor == 1.0 for d in dims)  # created while DIMSCALE was 1, not 100
    assert _doc(metric_app).vars["DIMSCALE"] == 100.0


def test_an_unreadable_dimscale_is_never_overwritten_by_a_plan_but_is_set_by_the_dimension_tool(metric_app):
    doc = _doc(metric_app)
    original_get, original_set = doc.GetVariable, doc.SetVariable
    sets = []

    def get(name):
        if name == "DIMSCALE":
            raise com_error("Unavailable")
        return original_get(name)

    def set_(name, value):
        if name == "DIMSCALE":
            sets.append(value)
        return original_set(name, value)

    doc.GetVariable, doc.SetVariable = get, set_
    _draw(_columns)
    assert sets == []  # it could not be put back, so the plan left it alone
    result = annotation.add_dimension("linear", [0, 0], [3000, 0], [0, -600], drawing_scale=35)
    assert sets == [35.0] and result["drawing_scale"] == 35.0  # the tool's scale is kept, as it always is


def test_dimensions_without_a_text_height_still_leave_the_drawings_scale_alone(app):
    from domain.architecture import Plan, Primitive
    from backends.targets import ComTarget, emit

    plan = Plan()
    plan.layer("A-DIM", 6)
    plan.add(Primitive("dim_linear", "A-DIM", "d", points=((0, 0, 0), (100, 0, 0)), location=(0, -10, 0), rotation=0.0))
    _doc(app).vars["DIMSCALE"] = 25.0
    emit(plan, ComTarget(_doc(app)))
    dim = _only_dimension(app)
    assert dim.ScaleFactor == 25.0 and not hasattr(dim, "TextHeight")  # the style, scale included, as before
    assert _doc(app).vars["DIMSCALE"] == 25.0


# ======= bug 2: inch and foot marks =======


def test_text_with_escaped_inch_marks_is_drawn_clean_through_com(app):
    sent = f"LIVING 12{BS}'-6{BS}\" x 10{BS}'-0{BS}\""
    single = drawing.draw_text(sent, [0, 0], 6.0)
    multi = annotation.draw_mtext(f"LIVING{BS}P{sent}\nSOUTH", [0, 20], 6.0)
    assert single["text"] == LABEL and single["text_requested"] == sent
    assert multi["text"] == f"LIVING{BS}P{LABEL}{BS}PSOUTH"
    texts = [e.TextString for e in _items(app)]
    assert texts == [LABEL, f"LIVING{BS}P{LABEL}{BS}PSOUTH"]


def test_text_typed_normally_is_not_reported_as_changed(app):
    single = drawing.draw_text(LABEL, [0, 0], 6.0)
    multi = annotation.draw_mtext(f"A{BS}P{LABEL}", [0, 20], 6.0)
    assert single["text"] == LABEL and "text_requested" not in single and "text_requested" not in multi


def test_dimension_text_override_is_cleaned_through_com(app):
    result = annotation.add_dimension("linear", [0, 0], [120, 0], [0, -24], text_override=f"10{BS}'-0{BS}\"")
    assert _only_dimension(app).TextOverride == "10'-0\"" and result["text_requested"] == f"10{BS}'-0{BS}\""


def test_room_labels_are_drawn_clean_through_com(metric_app):
    from domain import architecture

    rooms = [{"name": f"Bed 12{BS}'x10{BS}\"", "x": 0, "y": 0, "width": 5, "depth": 4}]
    _draw(lambda c: architecture.plan_room_floor_plan(rooms, units.unit_code("m"), c, windows="none",
                                                      dimensions=False))
    labels = [e.TextString for e in _on(metric_app, "A-TEXT", "AcDbMText")]
    assert len(labels) == 1 and labels[0].startswith("Bed 12'x10\"" + BS + "P") and BS + "\"" not in labels[0]
