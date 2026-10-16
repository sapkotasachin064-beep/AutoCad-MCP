"""Regression: the V0.3.0 plan engine draws exactly what V0.2.3 drew.

tests/golden/floor_plan_v0_2_3.json was produced by running the original
V0.2.3 generate_2d_floor_plan (git 3cf9254) against tests/fakes.py; see
tests/golden/make_floor_plan_golden.py. Entities, order, layers, geometry and
layer colors must match.
"""

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import session
from fakes import FakeApp
from golden.make_floor_plan_golden import record
from tools import architectural

GOLDEN = json.loads((Path(__file__).parent / "golden" / "floor_plan_v0_2_3.json").read_text(encoding="utf-8"))


def _same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(a, b, abs_tol=1e-6)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("AUTOCAD_MCP_UNITS", raising=False)
    session.unpin_document()
    session.set_units_override(None)


@pytest.mark.parametrize("case", sorted(GOLDEN["cases"]))
def test_v030_floor_plan_matches_v023_entity_for_entity(monkeypatch, case):
    golden = GOLDEN["cases"][case]
    app = FakeApp()
    monkeypatch.setattr("tools.architectural.get_connected_app", lambda: app)
    result = architectural.generate_2d_floor_plan(**golden["kwargs"])
    drawn = record(app.ActiveDocument)
    assert len(drawn) == len(golden["entities"])
    for index, (new, old) in enumerate(zip(drawn, golden["entities"])):
        assert new.keys() == old.keys(), f"entity {index}"
        for key in old:
            assert _same(new[key], old[key]), f"entity {index} ({old['object_name']}) differs in {key}"
    colors = {k: v.Color for k, v in app.ActiveDocument.Layers._items.items()}
    assert colors == golden["layer_colors"]
    assert result["verified"] is True and result["entity_count"] == len(drawn)


def test_result_shape_is_v023_compatible(monkeypatch):
    app = FakeApp()
    monkeypatch.setattr("tools.architectural.get_connected_app", lambda: app)
    result = architectural.generate_2d_floor_plan()
    assert set(result) >= {"status", "width_ft", "length_ft", "units", "exterior_walls", "interior_walls", "rooms",
                           "doors", "windows", "drawing_identity", "message"}
    assert len(result["exterior_walls"]) == 4 and all(result["exterior_walls"])
    door = result["doors"][0]
    assert {"room", "kind", "hinge_point", "latch_point", "leaf_end", "width", "angle_deg", "hinge_jamb_handle",
            "latch_jamb_handle", "leaf_handle", "arc_handle"} <= set(door)
    assert result["rooms"][0]["bounds"] == [4.5, 4.5, 283.5, 121.5]


def test_dry_run_draws_nothing(monkeypatch):
    app = FakeApp()
    monkeypatch.setattr("tools.architectural.get_connected_app", lambda: app)
    result = architectural.generate_2d_floor_plan(dry_run=True)
    assert app.ActiveDocument.ModelSpace.Count == 0
    assert result["dry_run"] is True and result["plan"]["primitive_count"] == 50
    assert result["exterior_walls"] == [None, None, None, None]


def test_metric_drawing_gets_the_same_plan_in_millimetres(monkeypatch):
    monkeypatch.setenv("AUTOCAD_MCP_UNITS", "metric_mm")
    app = FakeApp()
    monkeypatch.setattr("tools.architectural.get_connected_app", lambda: app)
    result = architectural.generate_2d_floor_plan()
    assert result["drawing_unit"] == "mm"
    # 24 ft = 7315.2 mm; first room's inner corner 4.5 in = 114.3 mm
    assert result["rooms"][0]["bounds"][0] == pytest.approx(114.3)
    first_wall = app.ActiveDocument.ModelSpace._items[0]
    assert max(first_wall.Coordinates) == pytest.approx(7315.2)


def test_feet_report_adds_bounds_in_feet(monkeypatch):
    app = FakeApp()
    monkeypatch.setattr("tools.architectural.get_connected_app", lambda: app)
    result = architectural.generate_2d_floor_plan(units="FEET")
    assert result["rooms"][0]["bounds_ft"][2] == pytest.approx(283.5 / 12.0)
