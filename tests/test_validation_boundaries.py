"""Every tool validates its arguments before it ever calls
connection.get_connected_app(), so bad input fails fast without touching
AutoCAD. These tests patch get_connected_app to raise if called, proving
invalid input never reaches COM in each module.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "MCP"))

from autocad import editing, entities, geometry, layers, scanning


def _forbid_com_call(module: str):
    return patch(
        f"autocad.{module}.get_connected_app",
        side_effect=AssertionError("validation should have failed before touching AutoCAD"),
    )


def test_draw_line_rejects_bad_point():
    with _forbid_com_call("entities"):
        with pytest.raises(geometry.ValidationError):
            entities.draw_line([0, 0, 0], ["x", 1, 0])


def test_draw_circle_rejects_negative_radius():
    with _forbid_com_call("entities"):
        with pytest.raises(geometry.ValidationError):
            entities.draw_circle([0, 0], -5)


def test_draw_polyline_rejects_single_point():
    with _forbid_com_call("entities"):
        with pytest.raises(geometry.ValidationError):
            entities.draw_polyline([[0, 0]])


def test_draw_rectangle_rejects_ambiguous_args():
    with _forbid_com_call("entities"):
        with pytest.raises(geometry.ValidationError):
            entities.draw_rectangle(corner1=[0, 0], corner2=[1, 1], base_point=[0, 0], width=1, height=1)


def test_draw_rectangle_rejects_no_args():
    with _forbid_com_call("entities"):
        with pytest.raises(geometry.ValidationError):
            entities.draw_rectangle()


def test_draw_rectangle_rejects_mismatched_plane():
    with _forbid_com_call("entities"):
        with pytest.raises(geometry.ValidationError):
            entities.draw_rectangle(corner1=[0, 0, 0], corner2=[1, 1, 5])


def test_draw_text_rejects_non_positive_height():
    with _forbid_com_call("entities"):
        with pytest.raises(geometry.ValidationError):
            entities.draw_text("hello", [0, 0], 0)


def test_move_entity_rejects_bad_handle():
    with _forbid_com_call("editing"):
        with pytest.raises(geometry.ValidationError):
            editing.move_entity("not a handle!", [1, 0, 0])


def test_rotate_entity_rejects_bad_base_point():
    with _forbid_com_call("editing"):
        with pytest.raises(geometry.ValidationError):
            editing.rotate_entity("2A", [0, "y", 0], 90)


def test_copy_entity_rejects_bad_displacement():
    with _forbid_com_call("editing"):
        with pytest.raises(geometry.ValidationError):
            editing.copy_entity("2A", [1, 2])


def test_highlight_entity_rejects_bad_method():
    with _forbid_com_call("editing"):
        with pytest.raises(geometry.ValidationError):
            editing.highlight_entity("2A", method="sparkly")


def test_highlight_entity_rejects_bad_color_for_persistent():
    with _forbid_com_call("editing"):
        with pytest.raises(geometry.ValidationError):
            editing.highlight_entity("2A", method="persistent", color=999)


def test_highlight_text_matches_rejects_bad_regex():
    with _forbid_com_call("editing"):
        with pytest.raises(geometry.ValidationError):
            editing.highlight_text_matches("(unclosed", use_regex=True)


def test_query_and_highlight_rejects_bad_method():
    with _forbid_com_call("editing"):
        with pytest.raises(geometry.ValidationError):
            editing.query_and_highlight("SELECT handle FROM entities", method="sparkly")


def test_query_and_highlight_rejects_missing_handle_column():
    with _forbid_com_call("editing"):
        with pytest.raises(geometry.ValidationError):
            editing.query_and_highlight("SELECT 1 AS not_handle")


def test_create_layer_rejects_bad_name():
    with _forbid_com_call("layers"):
        with pytest.raises(geometry.ValidationError):
            layers.create_layer("")


def test_create_layer_rejects_bad_color():
    with _forbid_com_call("layers"):
        with pytest.raises(geometry.ValidationError):
            layers.create_layer("Walls", color_index=1000)


def test_count_text_patterns_rejects_empty_pattern():
    with _forbid_com_call("scanning"):
        with pytest.raises(geometry.ValidationError):
            scanning.count_text_patterns("")


def test_count_text_patterns_rejects_bad_regex():
    with _forbid_com_call("scanning"):
        with pytest.raises(geometry.ValidationError):
            scanning.count_text_patterns("(unclosed", use_regex=True)
