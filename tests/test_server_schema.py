"""Tool registration and argument-schema checks. Imports server.py directly
(no AutoCAD, no subprocess) -- see test_e2e_mcp.py for real client discovery
and invocation over stdio."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import server

EXPECTED_V0_1_TOOLS = {
    "autocad_get_status",
    "autocad_launch_application",
    "autocad_create_test_drawing_with_line",
}

EXPECTED_V0_2_TOOLS = {
    "autocad_create_new_drawing",
    "autocad_draw_line",
    "autocad_draw_polyline",
    "autocad_draw_rectangle",
    "autocad_draw_circle",
    "autocad_draw_text",
    "autocad_create_layer",
    "autocad_move_entity",
    "autocad_rotate_entity",
    "autocad_copy_entity",
    "autocad_highlight_entity",
    "autocad_highlight_text_matches",
    "autocad_scan_all_entities",
    "autocad_count_text_patterns",
    "autocad_execute_query",
}

EXPECTED_V0_2_1_TOOLS = {
    "autocad_query_and_highlight",
}

EXPECTED_V0_2_2_TOOLS = {
    "autocad_ensure_layer",
    "autocad_draw_wall",
}


def _list_tools():
    return asyncio.run(server.server.list_tools())


def test_v01_tools_still_registered():
    names = {tool.name for tool in _list_tools()}
    assert EXPECTED_V0_1_TOOLS <= names


def test_v02_tools_all_registered():
    names = {tool.name for tool in _list_tools()}
    assert EXPECTED_V0_2_TOOLS <= names


def test_v021_tools_all_registered():
    names = {tool.name for tool in _list_tools()}
    assert EXPECTED_V0_2_1_TOOLS <= names


def test_v022_tools_all_registered():
    names = {tool.name for tool in _list_tools()}
    assert EXPECTED_V0_2_2_TOOLS <= names


def test_no_duplicate_tool_names():
    names = [tool.name for tool in _list_tools()]
    assert len(names) == len(set(names))


def test_exactly_21_tools_total():
    names = {tool.name for tool in _list_tools()}
    assert names == EXPECTED_V0_1_TOOLS | EXPECTED_V0_2_TOOLS | EXPECTED_V0_2_1_TOOLS | EXPECTED_V0_2_2_TOOLS


def test_draw_wall_schema_has_thickness_and_layer_defaults():
    tools = {tool.name: tool for tool in _list_tools()}
    schema = tools["autocad_draw_wall"].input_schema
    assert {"start_point", "end_point", "thickness", "layer"} <= schema["properties"].keys()
    assert set(schema["required"]) == {"start_point", "end_point"}


def test_draw_rectangle_schema_has_optional_corner_and_size_params():
    tools = {tool.name: tool for tool in _list_tools()}
    schema = tools["autocad_draw_rectangle"].input_schema
    properties = schema["properties"]
    assert {"corner1", "corner2", "base_point", "width", "height", "layer"} <= properties.keys()
    # None of these are individually required; draw_rectangle itself enforces
    # "exactly one of the two modes" at runtime.
    assert "corner1" not in schema.get("required", [])


def test_execute_query_schema_requires_query_string():
    tools = {tool.name: tool for tool in _list_tools()}
    schema = tools["autocad_execute_query"].input_schema
    assert "query" in schema["required"]
    assert schema["properties"]["query"]["type"] == "string"


def test_query_and_highlight_schema_requires_query_string():
    tools = {tool.name: tool for tool in _list_tools()}
    schema = tools["autocad_query_and_highlight"].input_schema
    assert "query" in schema["required"]
    assert schema["properties"]["query"]["type"] == "string"


def test_move_entity_schema_requires_handle_and_displacement():
    tools = {tool.name: tool for tool in _list_tools()}
    schema = tools["autocad_move_entity"].input_schema
    assert set(schema["required"]) == {"handle", "displacement"}
