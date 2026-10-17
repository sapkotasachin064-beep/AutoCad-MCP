"""The macro plans drawn through ComTarget into tests/fakes.py, the recorded fake of AutoCAD's object model.

These prove which COM calls this code makes and in what order (entity kinds, layers and colours, hatch fills,
dimension sizing), not AutoCAD's behaviour: nothing here is evidence that a live AutoCAD accepts them.
tests/test_macros_headless.py draws the same plans into real DXF files."""

import math
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backends.targets import ComTarget, emit
from core import session
from domain import macros, units
from domain.architecture import Plan, Primitive
from fakes import FakeApp, FakeEntity, com_error
from tools import architectural


@pytest.fixture
def app(monkeypatch):
    fake = FakeApp()
    monkeypatch.setattr("tools.architectural.get_connected_app", lambda: fake)
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


def _draw(build, dry_run=False):
    plan, handles, identity, code = architectural.run_plan_com(build, dry_run=dry_run)
    return plan, handles, code


def _items(app):
    return app.ActiveDocument.ModelSpace._items


def _on(app, layer, object_name=None):
    return [e for e in _items(app) if e.Layer == layer and (object_name is None or e.ObjectName == object_name)]


def _layer_colors(app):
    return {name: layer.Color for name, layer in app.ActiveDocument.Layers._items.items()}


def test_staircase_goes_through_com_with_its_layers_and_colours(metric_app):
    plan, handles, code = _draw(lambda c: macros.plan_staircase([0, 0], 12, c))
    assert code == units.unit_code("mm") and len(handles) == len(plan.primitives) == 30
    assert Counter(e.Layer for e in _items(metric_app)) == {"A-FLOR-TRED": 11, "A-FLOR-RISR": 12, "A-FLOR-LAND": 1,
                                                          "A-FLOR-HRAL": 2, "A-ANNO-SYMB": 3, "A-ANNO-NOTE": 1}
    treads = _on(metric_app, "A-FLOR-TRED", "AcDbPolyline")  # 2D lightweight polylines, closed
    assert len(treads) == 11 and all(t.Closed for t in treads)
    assert len(_on(metric_app, "A-FLOR-RISR", "AcDbLine")) == 12 and len(_on(metric_app, "A-ANNO-SYMB", "AcDbCircle")) == 1
    note = _on(metric_app, "A-ANNO-NOTE", "AcDbMText")[0]
    assert note.TextString == "UP 12R" and note.Height == pytest.approx(150.0) and note.AttachmentPoint == 5
    assert {k: v for k, v in _layer_colors(metric_app).items() if k != "0"} == {
        "A-FLOR-TRED": 2, "A-FLOR-RISR": 8, "A-FLOR-LAND": 3, "A-FLOR-HRAL": 4, "A-ANNO-SYMB": 6, "A-ANNO-NOTE": 7}


def test_the_same_staircase_in_an_inch_drawing_is_inch_sized(app):
    plan, _, code = _draw(lambda c: macros.plan_staircase([0, 0], 12, c))
    assert code == units.unit_code("in")
    first = _on(app, "A-FLOR-TRED", "AcDbPolyline")[0]
    xs = first.Coordinates[0::2]
    assert max(xs) - min(xs) == pytest.approx(36.0)  # 36 in wide
    assert _on(app, "A-ANNO-NOTE", "AcDbMText")[0].Height == pytest.approx(6.0)


def test_columns_are_polyline_plus_solid_hatch_with_sized_dimensions(metric_app):
    plan, _, _ = _draw(lambda c: macros.plan_column_grid(c, x_spacings=[4000, 4000], y_spacings=[3000]))
    assert Counter(e.Layer for e in _items(metric_app)) == {"COLUMNS": 12, "COLUMNS-TEXT": 6, "COLUMNS-DIM": 4}
    hatches = _on(metric_app, "COLUMNS", "AcDbHatch")
    assert len(hatches) == 6 and all(h.PatternName == "SOLID" for h in hatches)
    assert len(_on(metric_app, "COLUMNS", "AcDbPolyline")) == 6  # the hatch boundaries were deleted again
    assert _layer_colors(metric_app)["COLUMNS"] == 5
    dims = _on(metric_app, "COLUMNS-DIM")
    assert len(dims) == 4 and {d.ObjectName for d in dims} == {"AcDbRotatedDimension"}
    for dim in dims:  # sized from the 150 mm text height, shown in whole millimetres
        assert dim.TextHeight == pytest.approx(150.0) and dim.ArrowheadSize == pytest.approx(150.0)
        assert dim.ExtensionLineExtend == pytest.approx(75.0) and dim.ExtensionLineOffset == pytest.approx(37.5)
        assert dim.TextGap == pytest.approx(37.5) and dim.PrimaryUnitsPrecision == 0
    assert sorted(d.Measurement for d in dims) == [3000.0, 4000.0, 4000.0, 8000.0] or \
        sorted(round(d.Measurement) for d in dims) == [3000, 4000, 4000, 8000]


def test_dimension_size_and_precision_follow_an_inch_drawing(app):
    _draw(lambda c: macros.plan_column_grid(c, x_spacings=[160], y_spacings=[120]))
    dims = _on(app, "COLUMNS-DIM")
    assert dims and all(d.TextHeight == pytest.approx(6.0) and d.PrimaryUnitsPrecision == 2 for d in dims)
    assert all(d.ArrowheadSize == pytest.approx(6.0) and d.TextGap == pytest.approx(1.5) for d in dims)


def test_dimensions_without_a_text_height_keep_the_drawings_dimension_style(app):
    plan = Plan()
    plan.layer("A-DIM", 6)
    plan.add(Primitive("dim_linear", "A-DIM", "d", points=((0, 0, 0), (100, 0, 0)), location=(0, -10, 0), rotation=0.0))
    plan.add(Primitive("dim_aligned", "A-DIM", "a", points=((0, 0, 0), (60, 80, 0)), location=(0, -10, 0)))
    emit(plan, ComTarget(app.ActiveDocument))
    for dim in _items(app):
        assert not hasattr(dim, "TextHeight") and not hasattr(dim, "PrimaryUnitsPrecision")


def test_a_dimension_property_autocad_refuses_becomes_a_notice_not_a_failure(metric_app, monkeypatch):
    class Picky(FakeEntity):
        def __setattr__(self, name, value):
            if name == "TextGap":
                raise com_error("Invalid input")
            super().__setattr__(name, value)

    space = metric_app.ActiveDocument.ModelSpace
    original = space.AddDimRotated

    def add(p1, p2, loc, rot):
        entity = original(p1, p2, loc, rot)
        entity.__class__ = Picky  # from now on this dimension refuses TextGap
        return entity

    monkeypatch.setattr(space, "AddDimRotated", add)
    (plan, handles, identity, code), notices = session.collect(lambda: architectural.run_plan_com(
        lambda c: macros.plan_column_grid(c, x_spacings=[4000], y_spacings=[3000], labels=False), dry_run=False))
    assert len(handles) == len(plan.primitives)  # everything was still drawn
    skipped = [n for n in notices if n["kind"] == "dimension_size_not_applied"]
    assert len(skipped) == 2 and {n["property"] for n in skipped} == {"TextGap"}
    dim = _on(metric_app, "COLUMNS-DIM")[0]
    assert dim.TextHeight == pytest.approx(150.0)  # the other properties were applied


def test_window_wall_pieces_are_3d_polylines_like_every_other_wall(metric_app):
    wall = macros.explicit_wall([0, 0], [5000, 0], 230, units.unit_code("mm"), layer="A-WALL-EXT")
    plan, handles, _ = _draw(lambda c: macros.plan_wall_window(wall, "W2", c))
    pieces = _on(metric_app, "A-WALL-EXT", "AcDb3dPolyline")
    assert len(pieces) == 2 and all(p.Closed for p in pieces) and len(handles) == len(plan.primitives)
    assert Counter(e.Layer for e in _items(metric_app)) == {"A-WALL-EXT": 2, "A-GLAZ-SILL": 2, "A-GLAZ": 4, "A-GLAZ-IDEN": 1}
    assert _layer_colors(metric_app)["A-WALL-EXT"] == 3 and _layer_colors(metric_app)["A-GLAZ"] == 4
    assert _on(metric_app, "A-GLAZ-IDEN", "AcDbMText")[0].TextString == "W2"


@pytest.mark.parametrize("kind", sorted(macros.FURNITURE_TYPES))
def test_furniture_goes_through_com_on_a_furn(metric_app, kind):
    plan, handles, _ = _draw(lambda c: macros.plan_furniture(kind, [1000, 1000], c, rotation_degrees=30, label=True))
    assert len(handles) == len(plan.primitives) and len(_items(metric_app)) == len(plan.primitives)
    layers = Counter(e.Layer for e in _items(metric_app))
    assert layers["A-FURN"] == len(plan.primitives) - 1 and layers["A-FURN-TEXT"] == 1
    assert _layer_colors(metric_app)["A-FURN"] == 30
    if kind == "wc":
        arcs = _on(metric_app, "A-FURN", "AcDbArc")
        assert len(arcs) == 2 and arcs[0].StartAngle == pytest.approx(math.radians(180 + 30))


def test_dry_run_through_com_draws_nothing(metric_app):
    plan, handles, _ = _draw(lambda c: macros.plan_staircase([0, 0], 12, c), dry_run=True)
    assert handles is None and plan.meta["staircase"]["tread_count"] == 11 and not _items(metric_app)
