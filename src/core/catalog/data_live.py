"""Live AutoCAD evidence: catalog entries promoted to `verified`.

An entry is listed here only when a test in tests/test_integration_autocad.py
asserted that capability against a real AutoCAD and the run's output is
recorded in docs/testing.md. Merely calling a tool during a live test is not
enough (for example the generator test calls autocad_check_drawing but asserts
none of its rules, so the QC entries stay `tested`).

Keys are "<category letter>:<slug>"; values name the live test(s).
"""

LIVE_RUN = {
    "date": "2026-10-16",
    "autocad": "AutoCAD 2024 (R24.3, 24.3s (LMS Tech)), Windows 11",
    "command": "python -m pytest tests/test_integration_autocad.py -v",
    "result": "19 passed (two consecutive runs, after two fixes found by the first run)",
    "record": "docs/testing.md#live-autocad-results",
}

LIVE_VERIFIED = {
    # session, discovery, launch
    "B:com_thread": "test_v030_generators_live (server tools through ComBackend and the COM executor)",
    "B:session_units": "test_v030_list_drawings_and_units",
    "C:release_detection": "launch_and_wait / get_status: 24.3 -> 2024",
    "D:status": "every live test's skip gate (get_status connected + supported)",
    "D:install_detection": "get_status installed=True",
    "D:launch": "cad_engine.launch_and_wait from not running to connected",
    # documents
    "E:new_drawing": "fresh_drawing fixture, test_create_new_drawing_becomes_active",
    "E:list_drawings": "test_v030_list_drawings_and_units",
    "E:identity_model": "test_v030_list_drawings_and_units, test_v030_save_as_then_close",
    # inspection
    "F:summary": "test_v030_summary_list_and_detail",
    "F:scan_sqlite": "test_scan_all_entities_and_execute_query_round_trip",
    "F:text_search": "test_count_text_patterns_literal_and_regex",
    # entities and editing
    "G:list_entities": "test_v030_summary_list_and_detail",
    "G:get_entity": "test_v030_summary_list_and_detail",
    "G:move": "test_move_rotate_copy_entity",
    "G:rotate": "test_move_rotate_copy_entity",
    "G:copy": "test_move_rotate_copy_entity",
    "G:scale": "test_v030_modify_suite",
    "G:mirror": "test_v030_modify_suite",
    "G:offset": "test_v030_modify_suite",
    "G:array_rect": "test_v030_modify_suite",
    "G:delete_dry_run": "test_v030_modify_suite",
    "G:delete_verified": "test_v030_modify_suite",
    "G:set_properties": "test_v030_modify_suite",
    "G:highlight_temporary": "test_highlight_entity_temporary_preserves_color",
    "G:highlight_persistent": "test_highlight_entity_persistent_changes_color",
    "G:highlight_text": "test_highlight_text_matches_does_not_modify_text",
    "O:filter_by_type": "test_v030_summary_list_and_detail",
    "O:filter_by_layer": "test_v030_summary_list_and_detail",
    "P:dry_run_delete": "test_v030_modify_suite",
    # primitives and annotation
    "H:line": "test_draw_line_creates_real_entity",
    "H:polyline_3d": "test_draw_rectangle_and_polyline",
    "H:rectangle": "test_draw_rectangle_and_polyline",
    "H:circle": "test_draw_circle_and_create_layer",
    "H:arc": "test_v030_annotation_live",
    "M:angle_conversion": "test_v030_annotation_live (arc end angle reads back as 90 degrees)",
    "I:text": "test_draw_text",
    "I:mtext": "test_v030_annotation_live",
    "I:dim_aligned": "test_v030_annotation_live",
    "I:dim_linear": "test_v030_annotation_live",
    "I:dim_measurement_check": "test_v030_annotation_live",
    # layers, blocks, hatch
    "J:layer_create": "test_draw_circle_and_create_layer",
    "J:layer_on_demand": "test_v030_summary_list_and_detail, test_v030_modify_suite",
    "J:block_list": "test_v030_blocks_live",
    "J:block_insert": "test_v030_blocks_live",
    "J:attributes_on_insert": "test_v030_blocks_live",
    "J:attributes_update": "test_v030_blocks_live",
    "K:hatch_points": "test_v030_annotation_live",
    "K:hatch_pattern_verified": "test_v030_annotation_live (ANSI31 reads back; settles the pattern-type constant)",
    "K:hatch_area": "test_v030_annotation_live",
    # units
    "M:set_units": "test_v030_list_drawings_and_units",
    # output
    "L:layout_list": "test_v030_export_and_plot_live",
    "L:layout_restore_after_plot": "test_v030_export_and_plot_live",
    "T:plot_settings_restored": "test_v030_export_and_plot_live",
    "T:pdf_verification": "test_v030_export_and_plot_live",
    "R:export_dxf_copy": "test_v030_export_and_plot_live",
    # generators
    "P:count_verification": "test_v030_generators_live",
    "W:legacy_grid_plan": "test_v030_generators_live (50 entities, as in V0.2.3)",
    "W:room_plan": "test_v030_generators_live",
    "X:grid_lines": "test_v030_generators_live",
    "AG:plan_emitter": "test_v030_generators_live",
    # tooling
    "AN:live_tests": "this run",
}
