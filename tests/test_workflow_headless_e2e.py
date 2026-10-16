"""End-to-end residential workflow on the headless backend, through the
same public tool functions an MCP client calls (in-process), plus one real
stdio session with AUTOCAD_MCP_BACKEND=dxf. Files land in tmp_path and are
read back independently with ezdxf."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

ezdxf = pytest.importorskip("ezdxf")

import backends  # noqa: E402
import server  # noqa: E402
from core import session  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

ROOMS = [
    {"name": "Living", "x": 0, "y": 0, "width": 4.5, "depth": 4.0},
    {"name": "Kitchen", "x": 4.5, "y": 0, "width": 3.0, "depth": 4.0},
    {"name": "Bedroom", "x": 0, "y": 4.0, "width": 4.5, "depth": 3.6},
    {"name": "Bath", "x": 4.5, "y": 4.0, "width": 3.0, "depth": 3.6},
]


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


def test_residential_workflow(headless):
    tmp = headless
    created = server.autocad_create_new_drawing(pin=True)
    assert created["backend"] == "dxf" and created["state"]["executed"] is True
    units_result = server.autocad_set_drawing_units("metric_mm")
    assert units_result["insunits_name"] == "mm"

    dry = server.autocad_generate_floor_plan(rooms=ROOMS, unit="m", dry_run=True)
    assert dry["dry_run"] is True and dry["state"]["executed"] is False
    assert server.autocad_drawing_summary()["model_space_entities"] == 0

    plan = server.autocad_generate_floor_plan(rooms=ROOMS, unit="m")
    assert plan["verified"] is True and plan["state"]["verified"] is True and plan["state"]["saved"] is False
    assert len(plan["rooms"]) == 4 and plan["unreachable_rooms"] == []
    assert {d["kind"] for d in plan["doors"]} == {"main", "interior"}

    grid = server.autocad_draw_structural_grid(x_spacings=[4.5, 3.0], y_spacings=[4.0, 3.6], unit="m",
                                               column_size=[0.3, 0.3], origin=[0, 0])
    assert grid["verified"] is True and len(grid["columns"]) == 9

    stair = server.autocad_draw_stair_plan(floor_to_floor=3000, unit="mm", origin=[9000, 0])
    assert stair["design"]["risers"] == 16
    sheet = server.autocad_draw_sheet(paper="A3", scale=100, origin=[-5000, -5000],
                                      fields={"project": "Test house", "drawn_by": "MCP"})
    assert sheet["sheet_size_drawing_units"] == [pytest.approx(42000), pytest.approx(29700)]

    check = server.autocad_check_drawing()
    assert check["status"] == "ok" and check["entity_count"] > 0
    qty = server.autocad_quantity_takeoff(wall_height=3000)
    assert "A-WALL-EXT" in qty["layers"] and qty["metres_per_drawing_unit"] == pytest.approx(0.001)
    assert qty["layers"]["A-WALL-EXT"]["walls"]["count"] > 0

    for fmt in ("json", "csv", "md"):
        report = server.autocad_save_report(report="qc" if fmt != "csv" else "takeoff",
                                            path=str(tmp / f"report.{fmt}"), format=fmt)
        assert report["file"]["size_bytes"] > 0 and len(report["file"]["sha256"]) == 64

    first = server.autocad_save_drawing(path=str(tmp / "rev1.dxf"))
    assert first["state"]["saved"] is True and first["pin_moved"]["to"].endswith("rev1.dxf")
    doc = ezdxf.readfile(str(tmp / "rev1.dxf"))
    assert doc.header["$INSUNITS"] == 4
    assert {"A-WALL-EXT", "A-WALL-INT", "A-DOOR", "A-GLAZ", "A-TEXT", "S-GRID", "G-ANNO-TTLB"} <= {
        e.dxf.layer for e in doc.modelspace()}

    # A second revision: one wall-label edit and an extra line, then compare files.
    text = server.autocad_list_entities(entity_types=["MTEXT"], limit=1)["entities"][0]["handle"]
    server.autocad_move_entity(handle=text, displacement=[100, 0, 0])
    server.autocad_draw_line(start_point=[0, -2000], end_point=[7500, -2000], layer="A-ANNO")
    server.autocad_save_drawing(path=str(tmp / "rev2.dxf"))
    comparison = server.autocad_compare_dxf(path_a=str(tmp / "rev1.dxf"), path_b=str(tmp / "rev2.dxf"))
    assert comparison["summary"]["changed"] == 1 and comparison["summary"]["added"] == 1
    validation = server.autocad_validate_dxf_file(path=str(tmp / "rev2.dxf"))
    assert validation["valid"] is True and validation["insunits_name"] == "mm"


def test_errors_carry_codes_through_the_boundary(headless):
    with pytest.raises(ToolError) as info:
        server.autocad_draw_line(start_point=[0, 0], end_point=[1, 1])
    envelope = json.loads(str(info.value))
    assert envelope["error"]["code"] == "E_NO_ACTIVE_DOCUMENT" and envelope["backend"] == "dxf"
    server.autocad_create_new_drawing()
    with pytest.raises(ToolError) as info:
        server.autocad_plot_pdf(path="x.pdf")
    assert json.loads(str(info.value))["error"]["code"] == "E_UNSUPPORTED_BACKEND"
    with pytest.raises(ToolError) as info:
        server.autocad_generate_floor_plan(rooms=[{"name": "A", "width": -1, "depth": 2}], unit="m")
    assert json.loads(str(info.value))["error"]["code"] == "E_INVALID_INPUT"


def test_capabilities_report_the_headless_backend(headless):
    caps = server.autocad_get_capabilities()
    assert caps["backend"] == "dxf"
    assert caps["tools"]["autocad_plot_pdf"]["backends"] == ["com"]
    assert caps["tools"]["autocad_render_preview"]["backends"] == ["dxf"]
    assert "dxf" in caps["tools"]["autocad_generate_floor_plan"]["backends"]


async def _stdio_session(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, "AUTOCAD_MCP_BACKEND": "dxf", "AUTOCAD_MCP_OUTPUT_DIR": str(tmp_path)}
    params = StdioServerParameters(command=sys.executable, args=[str(Path(server.__file__))], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            await client.call_tool("autocad_create_new_drawing", {})
            drawn = await client.call_tool("autocad_draw_circle", {"center": [0, 0], "radius": 5})
            saved = await client.call_tool("autocad_save_drawing", {"path": str(tmp_path / "e2e.dxf")})
            refused = await client.call_tool("autocad_launch_application", {})
            return drawn, saved, refused


def test_real_stdio_session_on_the_headless_backend(tmp_path):
    drawn, saved, refused = asyncio.run(_stdio_session(tmp_path))
    assert drawn.is_error is False and json.loads(drawn.content[0].text)["backend"] == "dxf"
    assert saved.is_error is False and (tmp_path / "e2e.dxf").exists()
    assert refused.is_error is True
    assert json.loads(refused.content[0].text)["error"]["code"] == "E_UNSUPPORTED_BACKEND"
    doc = ezdxf.readfile(str(tmp_path / "e2e.dxf"))
    assert [e.dxftype() for e in doc.modelspace()] == ["CIRCLE"]
