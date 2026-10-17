"""MCP surface details: resources, prompts, the state block, configuration
errors, and headless import isolation."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import backends  # noqa: E402
import server  # noqa: E402
from core import registry, session  # noqa: E402
from core.errors import ConfigError  # noqa: E402
from domain import units  # noqa: E402


def _read(uri):
    contents = asyncio.run(server.server.read_resource(uri))
    return json.loads(list(contents)[0].content)


def test_capabilities_resource_matches_registry():
    data = _read("autocad://capabilities")
    assert {t["name"] for t in data["tools"]} == {t["name"] for t in registry.tools_list()}


def test_units_resource_lists_presets_and_defaults():
    data = _read("autocad://units")
    assert set(data["presets"]) == set(units.UNIT_PRESETS)
    assert data["drafting_defaults"]["metric_mm"]["exterior_wall"] == pytest.approx(230.0)
    assert data["drafting_defaults"]["imperial_inches"]["exterior_wall"] == pytest.approx(9.0)


def test_units_resource_lists_macro_sizes_window_types_and_annotation_scale():
    data = _read("autocad://units")
    assert data["macro_sizes"]["metric_mm"]["column"] == [300.0, 300.0]
    assert data["macro_sizes"]["imperial_inches"]["column"] == [9.0, 12.0]
    assert data["macro_sizes"]["metric_mm"]["stair_width"] == 900.0 and data["macro_sizes"]["imperial_inches"]["tread_depth"] == 10.0
    assert data["window_types"]["metric_mm"]["W2"] == {"name": "wide window", "sashes": 3, "width": 1800.0,
                                                      "height": 1200.0, "sill_height": 900.0}
    assert data["window_types"]["imperial_inches"]["W3"]["width"] == 24.0
    assert data["annotation_scale"]["metric_mm"]["text_height"] == 150.0
    assert data["annotation_scale"]["imperial_inches"]["text_height"] == 6.0
    assert data["annotation_scale"]["metric_mm"]["dimension"]["arrow"] == 150.0


def test_layer_standard_resource():
    data = _read("autocad://layer-standard")
    assert "A-WALL-EXT" in data["architectural"] and "S-GRID" in data["structural"]
    assert data["paper_sizes_mm"]["A3"] == [420.0, 297.0]


@pytest.mark.parametrize("name,needle", [("residential_floor_plan", "autocad_generate_floor_plan"),
                                         ("drawing_review", "autocad_check_drawing"),
                                         ("sheet_and_plot", "autocad_draw_sheet")])
def test_prompts_render(name, needle):
    result = asyncio.run(server.server.get_prompt(name, {}))
    text = " ".join(getattr(m.content, "text", "") for m in result.messages)
    assert needle in text


def test_state_block_separates_executed_verified_saved():
    spec = registry.specs()["autocad_draw_line"]
    state = server._with_state(spec, {"verified": True})["state"]
    assert state == {"accepted": True, "preflight_passed": True, "executed": True, "verified": True, "saved": False}
    dry = server._with_state(spec, {"dry_run": True, "verified": True})["state"]
    assert dry["executed"] is False and dry["verified"] is False
    read_spec = registry.specs()["autocad_get_status"]
    assert "state" not in server._with_state(read_spec, {})


def test_unknown_backend_is_a_config_error_not_a_fallback(monkeypatch):
    monkeypatch.setenv("AUTOCAD_MCP_BACKEND", "auto")
    backends._reset_for_tests()
    try:
        with pytest.raises(ConfigError) as info:
            session.backend_name()
        assert "no 'auto' mode" in info.value.message
    finally:
        monkeypatch.delenv("AUTOCAD_MCP_BACKEND")
        backends._reset_for_tests()


def test_unit_conversion_and_defaults():
    mm, inch, ft, m = (units.unit_code(u) for u in ("mm", "in", "feet", "metres"))
    assert units.convert(1.0, ft, inch) == pytest.approx(12.0)
    assert units.convert(1.0, inch, mm) == pytest.approx(25.4)
    assert units.convert(2500.0, mm, m) == pytest.approx(2.5)
    assert units.defaults_for(m)["exterior_wall"] == pytest.approx(0.23)
    assert units.defaults_for(ft)["interior_door"] == pytest.approx(2.5)
    with pytest.raises(Exception):
        units.unit_code("furlong")
    with pytest.raises(Exception) as info:
        units.mm_per_unit(0)
    assert info.value.code == "E_UNITS_MISMATCH"


def test_headless_backend_imports_no_pywin32_code():
    probe = (
        "import builtins, sys\n"
        f"sys.path.insert(0, {str(ROOT / 'src')!r})\n"
        "real = builtins.__import__\n"
        "def guard(name, *a, **k):\n"
        "    if name.split('.')[0] in ('pywintypes', 'pythoncom', 'win32com', 'cad_engine', 'com_engine', 'winreg'):\n"
        "        raise ImportError('blocked: ' + name)\n"
        "    return real(name, *a, **k)\n"
        "builtins.__import__ = guard\n"
        "import backends.dxf, backends.targets, domain.architecture\n"
        "import domain.analysis, core.reports, utils.validation\n"
        "print('ok')\n"
    )
    result = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
