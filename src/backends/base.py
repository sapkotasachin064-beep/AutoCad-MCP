"""The backend contract: one method per engine operation.

Every operation listed in Backend.OPERATIONS exists on this base class and
raises UnsupportedOperationError (E_UNSUPPORTED_BACKEND) naming the operation
and the backend. A backend supports an operation exactly when it overrides the
method -- core.registry.capability_map() reads support from that, so the
advertised capabilities cannot drift from what the code does. There is no
"returns ok: false" default: an unimplemented operation refuses loudly.
"""

from core.errors import UnsupportedOperationError


class Backend:
    name = "base"
    # Why a backend refuses an operation it does not override; shown to clients.
    UNSUPPORTED_REASONS: dict[str, str] = {}

    OPERATIONS = (
        # session / application
        "get_status", "launch_application", "active_drawing_identity",
        # documents
        "create_test_drawing_with_line", "create_new_drawing", "open_drawing", "save_drawing",
        "close_drawing", "list_drawings", "activate_drawing", "set_drawing_units",
        # primitives
        "draw_line", "draw_polyline", "draw_rectangle", "draw_circle", "draw_text",
        "draw_arc", "draw_mtext",
        # layers
        "create_layer", "ensure_layer", "list_layers", "set_layer_properties",
        # editing
        "move_entity", "rotate_entity", "copy_entity", "scale_entity", "mirror_entity",
        "offset_entity", "array_rectangular", "delete_entities", "set_entity_properties",
        "highlight_entity", "highlight_text_matches", "query_and_highlight",
        # query
        "drawing_summary", "list_entities", "get_entity", "scan_all_entities",
        "count_text_patterns", "snapshot_entities",
        # annotation
        "add_dimension", "add_hatch",
        # blocks
        "list_blocks", "insert_block", "get_block_attributes", "set_block_attributes",
        # output
        "list_layouts", "export_dxf", "plot_pdf", "render_preview",
        # composite drafting (runs a planned primitive list against the drawing)
        "draw_wall", "generate_2d_floor_plan", "emit_plan",
        # civil / survey
        "civil_alignment_station", "civil_station_point", "civil_ground_profile",
        "civil_surface_volumes", "civil_pipe_clearance", "civil_place_points",
    )

    def _unsupported(self, operation: str):
        return UnsupportedOperationError(operation, self.name, self.UNSUPPORTED_REASONS.get(operation, ""))


def _make_refusal(operation: str):
    def refuse(self, *args, **kwargs):
        raise self._unsupported(operation)

    refuse.__name__ = operation
    refuse.__qualname__ = f"Backend.{operation}"
    refuse.__doc__ = f"{operation}: not supported by this backend unless overridden."
    return refuse


for _operation in Backend.OPERATIONS:
    setattr(Backend, _operation, _make_refusal(_operation))
del _operation
