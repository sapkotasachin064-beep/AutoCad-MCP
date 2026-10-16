"""Read-only inspection over COM: drawing summary, filtered and paginated
entity listing, entity detail by handle, layer table, and the normalised
entity snapshot that QC, quantity takeoff and comparison work on.

Every function opens the drawing with for_write=False: no keystrokes, no unit
changes, nothing written. Entity iteration is bounded by max_entities and
every list reports `truncated` / `total` so a cut answer says it was cut.
"""

from collections import Counter

import cad_engine
from cad_engine import _retry_com, com_initialized, get_connected_app, get_drawing_identity
from core.evidence import page, validate_limit, validate_offset
from domain import units
import pywintypes

from tools._common import DXF_TYPES, as_list, bounding_box, dxf_type, model_space, point3, rad_to_deg, read
from tools._common import get_entity as lookup_entity
from utils import geometry, validation

DEFAULT_MAX_ENTITIES = 20000
MAX_VERTICES = 2000


def _open_read_only():
    app = get_connected_app()
    return cad_engine.get_active_document(app, for_write=False)


def _units_info(doc) -> dict:
    code = cad_engine.read_insunits(doc)
    lunits = cad_engine._get_variable(doc, "LUNITS")
    measurement = cad_engine._get_variable(doc, "MEASUREMENT")
    return {
        "insunits": code,
        "insunits_name": units.describe(code) if code is not None else None,
        "lunits": lunits,
        "measurement": {0: "imperial", 1: "metric"}.get(measurement, measurement),
    }


def _iterate(space, max_entities: int):
    count = _retry_com(lambda: space.Count)
    for index in range(min(count, max_entities)):
        try:
            yield _retry_com(lambda index=index: space.Item(index))
        except Exception:  # an entity AutoCAD refuses to hand out is skipped, not fatal
            continue


_validate_types = validation.validate_entity_types
_validate_layers = validation.validate_layer_filter
_validate_bbox = validation.validate_bbox
_inside = validation.box_inside


def drawing_summary(max_entities: int = DEFAULT_MAX_ENTITIES, max_layers: int = 200) -> dict:
    max_entities = validate_limit(max_entities, default=DEFAULT_MAX_ENTITIES, maximum=500000, label="max_entities")
    max_layers = validate_limit(max_layers, default=200, maximum=5000, label="max_layers")
    with com_initialized():
        doc = _open_read_only()
        space = model_space(doc)
        total = _retry_com(lambda: space.Count)
        by_type, by_layer = Counter(), Counter()
        for entity in _iterate(space, max_entities):
            by_type[dxf_type(read(entity, "ObjectName", "?"))] += 1
            by_layer[read(entity, "Layer", "?")] += 1

        layers = doc.Layers
        layer_names = [read(_retry_com(lambda i=i: layers.Item(i)), "Name") for i in range(_retry_com(lambda: layers.Count))]
        blocks = doc.Blocks
        block_names = []
        for i in range(_retry_com(lambda: blocks.Count)):
            block = _retry_com(lambda i=i: blocks.Item(i))
            if not read(block, "IsLayout", False) and not read(block, "IsXRef", False):
                name = read(block, "Name", "")
                if name and not name.startswith("*"):
                    block_names.append(name)
        layouts = doc.Layouts
        layout_names = [read(_retry_com(lambda i=i: layouts.Item(i)), "Name") for i in range(_retry_com(lambda: layouts.Count))]
        extmin = cad_engine._get_variable(doc, "EXTMIN")
        extmax = cad_engine._get_variable(doc, "EXTMAX")
        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "drawing_identity": identity.identity,
            "name": identity.name,
            "saved_to_disk": identity.saved,
            "unsaved_changes": not bool(read(doc, "Saved", True)),
            "read_only": bool(read(doc, "ReadOnly", False)),
            "units": _units_info(doc),
            "extents": {"min": point3(extmin), "max": point3(extmax)} if extmin is not None else None,
            "model_space_entities": total,
            "paper_space_entities": _retry_com(lambda: doc.PaperSpace.Count),
            "scanned_entities": min(total, max_entities),
            "truncated": total > max_entities,
            "counts_by_type": dict(by_type.most_common()),
            "counts_by_layer": dict(by_layer.most_common()),
            "layer_count": len(layer_names),
            "layers": layer_names[:max_layers],
            "layers_truncated": len(layer_names) > max_layers,
            "current_layer": read(read(doc, "ActiveLayer"), "Name"),
            "blocks": sorted(block_names)[:max_layers],
            "block_count": len(block_names),
            "layouts": layout_names,
            "message": f"{total} model-space entities on {len(layer_names)} layers.",
        }


def list_entities(entity_types=None, layers=None, bbox=None, offset: int = 0, limit: int = 100,
                  include_bbox: bool = False, max_entities: int = DEFAULT_MAX_ENTITIES) -> dict:
    wanted_types = _validate_types(entity_types)
    wanted_layers = _validate_layers(layers)
    window = _validate_bbox(bbox)
    offset = validate_offset(offset)
    limit = validate_limit(limit, default=100, maximum=5000)
    max_entities = validate_limit(max_entities, default=DEFAULT_MAX_ENTITIES, maximum=500000, label="max_entities")

    with com_initialized():
        doc = _open_read_only()
        space = model_space(doc)
        total_in_space = _retry_com(lambda: space.Count)
        rows = []
        for entity in _iterate(space, max_entities):
            kind = dxf_type(read(entity, "ObjectName", "?"))
            if wanted_types is not None and kind not in wanted_types:
                continue
            layer = read(entity, "Layer", "")
            if wanted_layers is not None and layer.lower() not in wanted_layers:
                continue
            box = bounding_box(entity) if (window is not None or include_bbox) else None
            if window is not None and (box is None or not _inside(box, window)):
                continue
            row = {"handle": read(entity, "Handle"), "type": kind, "layer": layer}
            if include_bbox:
                row["bbox"] = box
            rows.append(row)
        identity = get_drawing_identity(doc)
        window_page = page(rows, offset=offset, limit=limit)
        return {
            "status": "ok",
            "drawing_identity": identity.identity,
            "entities": window_page.pop("items"),
            **window_page,
            "scanned_entities": min(total_in_space, max_entities),
            "scan_truncated": total_in_space > max_entities,
            "filters": {"entity_types": sorted(wanted_types) if wanted_types else None,
                        "layers": layers, "bbox": bbox},
            "message": f"{window_page['total']} matching entities; returned {window_page['returned']}.",
        }


def _vertices(entity, kind: str):
    coords = [float(c) for c in as_list(read(entity, "Coordinates"))]
    step = 2 if kind == "LWPOLYLINE" else 3
    points = [coords[i:i + step] for i in range(0, len(coords) - step + 1, step)]
    return points


def describe_entity(entity, *, full: bool = True) -> dict:
    """Normalised dict for one COM entity. full=False keeps only what QC,
    takeoff and comparison need (and skips per-vertex detail beyond MAX_VERTICES)."""
    object_name = read(entity, "ObjectName", "?")
    kind = dxf_type(object_name)
    info = {"handle": read(entity, "Handle"), "type": kind, "layer": read(entity, "Layer")}
    if full:
        info.update(
            object_name=object_name,
            color=read(entity, "Color"),
            linetype=read(entity, "Linetype"),
            lineweight=read(entity, "Lineweight"),
            visible=read(entity, "Visible"),
        )
    if kind == "LINE":
        start, end = point3(read(entity, "StartPoint")), point3(read(entity, "EndPoint"))
        info.update(points=[start, end], length=read(entity, "Length"))
        if full:
            info["angle_degrees"] = rad_to_deg(read(entity, "Angle", 0.0) or 0.0)
    elif kind in ("LWPOLYLINE", "POLYLINE3D", "POLYLINE"):
        points = _vertices(entity, kind)
        closed = bool(read(entity, "Closed", False))
        info.update(points=points[:MAX_VERTICES], vertex_count=len(points), closed=closed,
                    length=read(entity, "Length"))
        if len(points) > MAX_VERTICES:
            info["points_truncated"] = True
        if closed and kind == "LWPOLYLINE":
            info["area"] = read(entity, "Area")
    elif kind == "CIRCLE":
        info.update(center=point3(read(entity, "Center")), radius=read(entity, "Radius"), area=read(entity, "Area"))
    elif kind == "ARC":
        info.update(
            center=point3(read(entity, "Center")),
            radius=read(entity, "Radius"),
            start_angle_degrees=rad_to_deg(read(entity, "StartAngle", 0.0) or 0.0),
            end_angle_degrees=rad_to_deg(read(entity, "EndAngle", 0.0) or 0.0),
            length=read(entity, "ArcLength"),
        )
    elif kind in ("TEXT", "MTEXT"):
        info.update(text=read(entity, "TextString"), insertion_point=point3(read(entity, "InsertionPoint")),
                    height=read(entity, "Height"))
        if full:
            info["rotation_degrees"] = rad_to_deg(read(entity, "Rotation", 0.0) or 0.0)
            if kind == "MTEXT":
                info["width"] = read(entity, "Width")
    elif kind == "INSERT":
        info.update(block=read(entity, "EffectiveName") or read(entity, "Name"),
                    insertion_point=point3(read(entity, "InsertionPoint")))
        if full:
            info.update(
                rotation_degrees=rad_to_deg(read(entity, "Rotation", 0.0) or 0.0),
                scale=[read(entity, "XScaleFactor"), read(entity, "YScaleFactor"), read(entity, "ZScaleFactor")],
            )
            if read(entity, "HasAttributes", False):
                info["attributes"] = block_attributes(entity)
    elif kind == "HATCH":
        info.update(pattern=read(entity, "PatternName"), area=read(entity, "Area"))
    elif kind == "DIMENSION":
        info.update(measurement=read(entity, "Measurement"))
        if full:
            info["text_override"] = read(entity, "TextOverride")
    elif kind == "ELLIPSE":
        info.update(center=point3(read(entity, "Center")), major_axis=point3(read(entity, "MajorAxis")),
                    ratio=read(entity, "RadiusRatio"), area=read(entity, "Area"))
    if full or kind not in ("LINE", "LWPOLYLINE", "POLYLINE3D", "POLYLINE", "CIRCLE", "ARC"):
        info["bbox"] = bounding_box(entity)
    return info


def block_attributes(entity) -> dict:
    """{tag: value} of a block reference's attributes ({} when it has none
    or AutoCAD will not list them)."""
    try:
        attributes = as_list(_retry_com(lambda: entity.GetAttributes()))
    except (pywintypes.com_error, AttributeError):
        return {}
    return {read(a, "TagString"): read(a, "TextString") for a in attributes}


def get_entity(handle: str) -> dict:
    handle = geometry.validate_handle(handle)
    with com_initialized():
        doc = _open_read_only()
        entity = lookup_entity(doc, handle)
        identity = get_drawing_identity(doc)
        return {"status": "ok", "drawing_identity": identity.identity, "entity": describe_entity(entity)}


def list_layers() -> dict:
    with com_initialized():
        doc = _open_read_only()
        current = read(read(doc, "ActiveLayer"), "Name")
        layers = doc.Layers
        rows = []
        for i in range(_retry_com(lambda: layers.Count)):
            layer = _retry_com(lambda i=i: layers.Item(i))
            name = read(layer, "Name")
            rows.append({
                "name": name,
                "on": read(layer, "LayerOn"),
                "frozen": read(layer, "Freeze"),
                "locked": read(layer, "Lock"),
                "color_index": read(layer, "Color"),
                "linetype": read(layer, "Linetype"),
                "lineweight": read(layer, "Lineweight"),
                "plottable": read(layer, "Plottable"),
                "current": name == current,
            })
        identity = get_drawing_identity(doc)
        return {"status": "ok", "drawing_identity": identity.identity, "count": len(rows), "layers": rows,
                "current_layer": current}


def snapshot_entities(max_entities: int = DEFAULT_MAX_ENTITIES) -> dict:
    """Normalised geometry of every top-level model-space entity (bounded)."""
    max_entities = validate_limit(max_entities, default=DEFAULT_MAX_ENTITIES, maximum=500000, label="max_entities")
    with com_initialized():
        doc = _open_read_only()
        space = model_space(doc)
        total = _retry_com(lambda: space.Count)
        entities = [describe_entity(e, full=False) for e in _iterate(space, max_entities)]
        identity = get_drawing_identity(doc)
        return {
            "drawing_identity": identity.identity,
            "units": _units_info(doc),
            "entities": entities,
            "total": total,
            "truncated": total > max_entities,
        }
