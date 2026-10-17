"""Live AutoCAD backend: every operation runs the COM implementation in
tools/* on the dedicated COM thread (core/com_executor.py) with a timeout,
collecting the notices it produced (units applied, command cancelled).

The tools/* functions are unchanged library functions that can still be
called directly (the live integration tests do); this class only decides
where and how long they run.
"""

import dataclasses
import os

import cad_engine
from backends.base import Backend
from core import session
from core.com_executor import get_executor
from core.errors import ConfigError
from tools import (
    analysis,
    annotation,
    architectural,
    blocks,
    civil,
    documents,
    editing,
    layers,
    modify,
    output,
    primitives,
    query,
)

DEFAULT_TIMEOUT_SECONDS = 120.0


def com_timeout() -> float:
    raw = os.environ.get("AUTOCAD_MCP_COM_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"AUTOCAD_MCP_COM_TIMEOUT={raw!r} is not a number of seconds") from None
    if value < 0:
        raise ConfigError("AUTOCAD_MCP_COM_TIMEOUT must be >= 0 (0 = no limit)")
    return value


class ComBackend(Backend):
    name = "com"
    UNSUPPORTED_REASONS = {
        "render_preview": "the live backend reports AutoCAD's own output; use autocad_plot_pdf",
    }

    def _call(self, label, func, /, *args, timeout=None, **kwargs):
        limit = com_timeout() if timeout is None else timeout

        def job():
            return session.collect(lambda: func(*args, **kwargs))

        result, notices = get_executor().run(job, timeout=limit, label=label)
        if isinstance(result, dict):
            result.setdefault("backend", self.name)
            if notices:
                result["notices"] = notices
        return result

    # ======= session / application =======

    def get_status(self):
        return self._call("get_status", lambda: dataclasses.asdict(cad_engine.get_status()))

    def launch_application(self, timeout_seconds: float = 60):
        # The executor deadline must outlast launch_and_wait's own polling.
        return self._call(
            "launch_application",
            lambda: dataclasses.asdict(cad_engine.launch_and_wait(timeout=timeout_seconds)),
            timeout=max(float(timeout_seconds), 0) + 30.0,
        )

    def active_drawing_identity(self):
        def read():
            with cad_engine.com_initialized():
                app = cad_engine.get_connected_app()
                count = cad_engine._retry_com(lambda: app.Documents.Count)
                if count == 0:
                    return None
                doc = cad_engine._retry_com(lambda: app.ActiveDocument)
                return cad_engine.get_drawing_identity(doc).identity

        return self._call("active_drawing_identity", read)

    # ======= documents =======

    def create_test_drawing_with_line(self, output_dir=None):
        return self._call("create_test_drawing_with_line", primitives.create_test_drawing_with_line,
                          output_dir=output_dir)

    def create_new_drawing(self, template=None, pin=False):
        return self._call("create_new_drawing", primitives.create_new_drawing, template=template, pin=pin)

    def list_drawings(self):
        return self._call("list_drawings", documents.list_drawings)

    def open_drawing(self, path, read_only=True, pin=False):
        return self._call("open_drawing", documents.open_drawing, path, read_only=read_only, pin=pin)

    def save_drawing(self, path=None, overwrite=False, format="dwg", version="R2018"):
        return self._call("save_drawing", documents.save_drawing, path=path, overwrite=overwrite,
                          format=format, version=version)

    def close_drawing(self, identity=None, discard_changes=False):
        return self._call("close_drawing", documents.close_drawing, identity=identity,
                          discard_changes=discard_changes)

    def activate_drawing(self, identity, pin=False):
        return self._call("activate_drawing", documents.activate_drawing, identity, pin=pin)

    def set_drawing_units(self, preset):
        return self._call("set_drawing_units", documents.set_drawing_units, preset)

    # ======= primitives =======

    def draw_line(self, start_point, end_point, layer=None):
        return self._call("draw_line", primitives.draw_line, start_point, end_point, layer=layer)

    def draw_polyline(self, points, closed=False, layer=None):
        return self._call("draw_polyline", primitives.draw_polyline, points, closed=closed, layer=layer)

    def draw_rectangle(self, corner1=None, corner2=None, base_point=None, width=None, height=None, layer=None):
        return self._call("draw_rectangle", primitives.draw_rectangle, corner1=corner1, corner2=corner2,
                          base_point=base_point, width=width, height=height, layer=layer)

    def draw_circle(self, center, radius, layer=None):
        return self._call("draw_circle", primitives.draw_circle, center, radius, layer=layer)

    def draw_text(self, text, insertion_point, height, rotation_degrees=0.0, layer=None):
        return self._call("draw_text", primitives.draw_text, text, insertion_point, height,
                          rotation_degrees=rotation_degrees, layer=layer)

    def draw_arc(self, center, radius, start_angle_degrees, end_angle_degrees, layer=None):
        return self._call("draw_arc", annotation.draw_arc, center, radius, start_angle_degrees,
                          end_angle_degrees, layer=layer)

    def draw_mtext(self, text, insertion_point, height, width=0.0, rotation_degrees=0.0, layer=None):
        return self._call("draw_mtext", annotation.draw_mtext, text, insertion_point, height, width=width,
                          rotation_degrees=rotation_degrees, layer=layer)

    # ======= annotation =======

    def add_dimension(self, kind, first_point, second_point, dimension_line_point, rotation_degrees=0.0,
                      text_override=None, layer=None):
        return self._call("add_dimension", annotation.add_dimension, kind, first_point, second_point,
                          dimension_line_point, rotation_degrees=rotation_degrees, text_override=text_override,
                          layer=layer)

    def add_hatch(self, boundary_handles=None, boundary_points=None, pattern="ANSI31", scale=1.0,
                  angle_degrees=0.0, layer=None, keep_boundary=True):
        return self._call("add_hatch", annotation.add_hatch, boundary_handles=boundary_handles,
                          boundary_points=boundary_points, pattern=pattern, scale=scale,
                          angle_degrees=angle_degrees, layer=layer, keep_boundary=keep_boundary)

    # ======= blocks =======

    def list_blocks(self, include_anonymous=False):
        return self._call("list_blocks", blocks.list_blocks, include_anonymous=include_anonymous)

    def insert_block(self, name, insertion_point, scale=1.0, rotation_degrees=0.0, layer=None, attributes=None):
        return self._call("insert_block", blocks.insert_block, name, insertion_point, scale=scale,
                          rotation_degrees=rotation_degrees, layer=layer, attributes=attributes)

    def get_block_attributes(self, handle):
        return self._call("get_block_attributes", blocks.get_block_attributes, handle)

    def set_block_attributes(self, handle, values):
        return self._call("set_block_attributes", blocks.set_block_attributes, handle, values)

    # ======= output =======

    def list_layouts(self):
        return self._call("list_layouts", output.list_layouts)

    def export_dxf(self, path, overwrite=False):
        return self._call("export_dxf", output.export_dxf, path, overwrite=overwrite)

    def plot_pdf(self, path, layout=None, paper=None, plot_style=None, overwrite=False):
        # Plotting a large sheet is legitimately slow; give it a longer deadline.
        return self._call("plot_pdf", output.plot_pdf, path, layout=layout, paper=paper, plot_style=plot_style,
                          overwrite=overwrite, timeout=max(com_timeout(), 300.0) if com_timeout() else 0)

    # ======= layers =======

    def create_layer(self, name, color_index=None, linetype=None):
        return self._call("create_layer", layers.create_layer, name, color_index=color_index, linetype=linetype)

    def ensure_layer(self, name, color_index=None, linetype=None):
        return self._call("ensure_layer", layers.ensure_layer, name, color_index=color_index, linetype=linetype)

    def list_layers(self):
        return self._call("list_layers", query.list_layers)

    def set_layer_properties(self, name, on=None, frozen=None, locked=None, color_index=None, linetype=None,
                             lineweight=None, plottable=None):
        return self._call("set_layer_properties", layers.set_layer_properties, name, on=on, frozen=frozen,
                          locked=locked, color_index=color_index, linetype=linetype, lineweight=lineweight,
                          plottable=plottable)

    # ======= editing =======

    def move_entity(self, handle, displacement):
        return self._call("move_entity", editing.move_entity, handle, displacement)

    def rotate_entity(self, handle, base_point, angle_degrees):
        return self._call("rotate_entity", editing.rotate_entity, handle, base_point, angle_degrees)

    def copy_entity(self, handle, displacement):
        return self._call("copy_entity", editing.copy_entity, handle, displacement)

    def highlight_entity(self, handle, method="temporary", color=1, clear=False):
        return self._call("highlight_entity", editing.highlight_entity, handle, method=method, color=color,
                          clear=clear)

    def highlight_text_matches(self, pattern, use_regex=False, method="temporary", color=1, clear=False,
                               limit=500):
        return self._call("highlight_text_matches", editing.highlight_text_matches, pattern,
                          use_regex=use_regex, method=method, color=color, clear=clear, limit=limit)

    def query_and_highlight(self, query, params=None, method="temporary", color=1, clear=False):
        return self._call("query_and_highlight", editing.query_and_highlight, query, params=params,
                          method=method, color=color, clear=clear)

    def scale_entity(self, handle, base_point, factor):
        return self._call("scale_entity", modify.scale_entity, handle, base_point, factor)

    def mirror_entity(self, handle, axis_start, axis_end, keep_original=True):
        return self._call("mirror_entity", modify.mirror_entity, handle, axis_start, axis_end,
                          keep_original=keep_original)

    def offset_entity(self, handle, distance):
        return self._call("offset_entity", modify.offset_entity, handle, distance)

    def array_rectangular(self, handle, rows, columns, row_spacing, column_spacing):
        return self._call("array_rectangular", modify.array_rectangular, handle, rows, columns, row_spacing,
                          column_spacing)

    def delete_entities(self, handles, dry_run=True):
        return self._call("delete_entities", modify.delete_entities, handles, dry_run=dry_run)

    def set_entity_properties(self, handles, layer=None, color_index=None, linetype=None, lineweight=None):
        return self._call("set_entity_properties", modify.set_entity_properties, handles, layer=layer,
                          color_index=color_index, linetype=linetype, lineweight=lineweight)

    # ======= query =======

    def drawing_summary(self, max_entities=20000):
        return self._call("drawing_summary", query.drawing_summary, max_entities=max_entities)

    def list_entities(self, entity_types=None, layers=None, bbox=None, offset=0, limit=100, include_bbox=False,
                      max_entities=20000):
        return self._call("list_entities", query.list_entities, entity_types=entity_types, layers=layers,
                          bbox=bbox, offset=offset, limit=limit, include_bbox=include_bbox,
                          max_entities=max_entities)

    def get_entity(self, handle):
        return self._call("get_entity", query.get_entity, handle)

    def snapshot_entities(self, max_entities=20000):
        return self._call("snapshot_entities", query.snapshot_entities, max_entities=max_entities)

    def scan_all_entities(self):
        return self._call("scan_all_entities", analysis.scan_all_entities)

    def count_text_patterns(self, pattern, use_regex=False, limit=500):
        return self._call("count_text_patterns", analysis.count_text_patterns, pattern,
                          use_regex=use_regex, limit=limit)

    # ======= architecture =======

    def draw_wall(self, start_point, end_point, thickness=None, layer="A-WALL"):
        return self._call("draw_wall", architectural.draw_wall, start_point, end_point,
                          thickness=thickness, layer=layer)

    def generate_2d_floor_plan(self, width_ft=24.0, length_ft=30.0, units="INCHES", rooms_config=None,
                               dry_run=False):
        return self._call("generate_2d_floor_plan", architectural.generate_2d_floor_plan,
                          width_ft=width_ft, length_ft=length_ft, units=units, rooms_config=rooms_config,
                          dry_run=dry_run)

    def emit_plan(self, build, dry_run=False):
        """build(drawing_insunits) -> Plan, drawn (or only planned, dry_run)
        into the active drawing on the COM thread. Returns
        ((plan, handles|None, identity, insunits), notices)."""

        def job():
            return session.collect(lambda: architectural.run_plan_com(build, dry_run=dry_run))

        return get_executor().run(job, timeout=com_timeout(), label="emit_plan")

    # ======= civil =======

    def civil_alignment_station(self, alignment, points, start_station=0.0):
        return self._call("civil_alignment_station", civil.alignment_station, alignment,
                          points=points, start_station=start_station)

    def civil_station_point(self, alignment, stations, offset=0.0, start_station=0.0):
        return self._call("civil_station_point", civil.station_point, alignment,
                          stations=stations, offset=offset, start_station=start_station)

    def civil_ground_profile(self, alignment, interval, layer=None, offset=0.0, method="idw", neighbours=8,
                             start_station=0.0, max_entities=20000):
        return self._call("civil_ground_profile", civil.ground_profile, alignment, interval,
                          layer=layer, offset=offset, method=method, neighbours=neighbours,
                          start_station=start_station, max_entities=max_entities)

    def civil_surface_volumes(self, existing_layer, design_layer, cell_size, method="idw", neighbours=8,
                              max_entities=20000):
        return self._call("civil_surface_volumes", civil.surface_volumes, existing_layer, design_layer,
                          cell_size, method=method, neighbours=neighbours, max_entities=max_entities)

    def civil_pipe_clearance(self, first, second, first_diameter=None, second_diameter=None):
        return self._call("civil_pipe_clearance", civil.pipe_clearance, first, second,
                          first_diameter=first_diameter, second_diameter=second_diameter)

    def civil_place_points(self, points, layer="C-POINT", label=True, text_height=None, start_number=1):
        return self._call("civil_place_points", civil.place_points, points,
                          layer=layer, label=label, text_height=text_height, start_number=start_number)
