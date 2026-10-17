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

EXPECTED_V0_2_3_TOOLS = {
    "autocad_generate_2d_floor_plan",
}

# V0.3.0 additions. Every V0.1-V0.2.3 tool above is kept with its name and
# required arguments; this set grows as V0.3.0 tools land.
EXPECTED_V0_3_0_TOOLS = {
    # foundation
    "autocad_get_capabilities",
    "autocad_pin_document",
    "autocad_unpin_document",
    # documents
    "autocad_list_drawings",
    "autocad_open_drawing",
    "autocad_save_drawing",
    "autocad_close_drawing",
    "autocad_activate_drawing",
    "autocad_set_drawing_units",
    # drawing
    "autocad_draw_arc",
    "autocad_draw_mtext",
    # layers
    "autocad_list_layers",
    "autocad_set_layer_properties",
    # editing
    "autocad_scale_entity",
    "autocad_mirror_entity",
    "autocad_offset_entity",
    "autocad_array_rectangular",
    "autocad_delete_entities",
    "autocad_set_entity_properties",
    # query
    "autocad_drawing_summary",
    "autocad_list_entities",
    "autocad_get_entity",
    # annotation
    "autocad_add_dimension",
    "autocad_add_hatch",
    # blocks
    "autocad_list_blocks",
    "autocad_insert_block",
    "autocad_get_block_attributes",
    "autocad_set_block_attributes",
    # output
    "autocad_list_layouts",
    "autocad_export_dxf",
    "autocad_plot_pdf",
    "autocad_render_preview",
    # residential / civil workflows
    "autocad_generate_floor_plan",
    "autocad_draw_structural_grid",
    "autocad_design_stair",
    "autocad_draw_stair_plan",
    "autocad_draw_sheet",
    # civil / survey
    "autocad_civil_alignment_station",
    "autocad_civil_station_point",
    "autocad_civil_ground_profile",
    "autocad_civil_surface_volumes",
    "autocad_civil_pipe_clearance",
    "autocad_civil_place_points",
    # analysis
    "autocad_check_drawing",
    "autocad_quantity_takeoff",
    "autocad_save_report",
    "autocad_compare_dxf",
    "autocad_validate_dxf_file",
}

# Architectural drawing macros: staircase, column grid, window cut into a wall, furniture stamps.
EXPECTED_MACRO_TOOLS = {
    "autocad_draw_staircase",
    "autocad_draw_column_grid",
    "autocad_draw_wall_window",
    "autocad_place_architectural_block",
}

LEGACY_TOOLS = (
    EXPECTED_V0_1_TOOLS | EXPECTED_V0_2_TOOLS | EXPECTED_V0_2_1_TOOLS | EXPECTED_V0_2_2_TOOLS | EXPECTED_V0_2_3_TOOLS
)
ALL_EXPECTED_TOOLS = LEGACY_TOOLS | EXPECTED_V0_3_0_TOOLS | EXPECTED_MACRO_TOOLS


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


def test_v023_tools_all_registered():
    names = {tool.name for tool in _list_tools()}
    assert EXPECTED_V0_2_3_TOOLS <= names


def test_no_duplicate_tool_names():
    names = [tool.name for tool in _list_tools()]
    assert len(names) == len(set(names))


def test_registered_tools_are_exactly_the_expected_set():
    # V0.2.3 asserted exactly 22 tools; V0.3.0 keeps all 22 and adds the
    # EXPECTED_V0_3_0_TOOLS set, so the total is pinned here instead.
    names = {tool.name for tool in _list_tools()}
    assert names == ALL_EXPECTED_TOOLS


def test_every_legacy_tool_is_still_registered():
    names = {tool.name for tool in _list_tools()}
    assert LEGACY_TOOLS <= names
    assert len(LEGACY_TOOLS) == 22


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


def test_generate_2d_floor_plan_schema_has_no_required_params():
    tools = {tool.name: tool for tool in _list_tools()}
    schema = tools["autocad_generate_2d_floor_plan"].input_schema
    assert {"width_ft", "length_ft", "units", "rooms_config"} <= schema["properties"].keys()
    assert not schema.get("required")


def test_macro_tools_are_registered():
    names = {tool.name for tool in _list_tools()}
    assert EXPECTED_MACRO_TOOLS <= names


def test_staircase_schema_takes_the_documented_arguments():
    schema = {t.name: t for t in _list_tools()}["autocad_draw_staircase"].input_schema
    assert {"start_point", "width", "tread_depth", "riser_count", "direction"} <= schema["properties"].keys()
    assert set(schema["required"]) == {"start_point", "riser_count"}
    assert schema["properties"]["riser_count"]["type"] == "integer"
    assert schema["properties"]["direction"]["default"] == "UP"
    assert schema["properties"]["rotation_degrees"]["default"] == 90.0


def test_column_grid_schema_defaults_to_the_columns_layer():
    schema = {t.name: t for t in _list_tools()}["autocad_draw_column_grid"].input_schema
    assert {"x_spacings", "y_spacings", "points", "at_wall_intersections", "column_size", "layer"} <= schema[
        "properties"].keys()
    assert schema["properties"]["layer"]["default"] == "COLUMNS"
    assert not schema.get("required")


def test_wall_window_schema_and_destructive_hint():
    tools = {t.name: t for t in _list_tools()}
    tool = tools["autocad_draw_wall_window"]
    assert {"window_type", "wall_handle", "wall_start", "wall_end", "offset", "trim_wall", "dry_run"} <= tool.input_schema[
        "properties"].keys()
    assert tool.input_schema["properties"]["window_type"]["default"] == "W1"
    assert tool.annotations.destructive_hint is True  # replacing a wall deletes its outline


def test_furniture_schema_requires_type_and_position_and_defaults_to_a_furn():
    schema = {t.name: t for t in _list_tools()}["autocad_place_architectural_block"].input_schema
    assert set(schema["required"]) == {"block_type", "position"}
    assert schema["properties"]["layer"]["default"] == "A-FURN"


def test_every_macro_parameter_has_a_description():
    tools = {t.name: t for t in _list_tools()}
    for name in EXPECTED_MACRO_TOOLS:
        for param, spec in tools[name].input_schema["properties"].items():
            assert spec.get("description"), f"{name}.{param} has no description"
