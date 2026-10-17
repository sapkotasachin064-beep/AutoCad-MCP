"""Civil and survey tools over ordinary AutoCAD entities: centreline
stationing, ground profiles from spot levels, grid cut/fill volumes, pipe
clearance, and COGO-style point placement with labels.

The maths lives in domain/civil.py; this module only reads and writes
drawing entities (LINE, polyline, POINT). No Civil 3D object, no Civil 3D
installation and no AutoLISP/command-line execution is involved. Spot levels
are POINT entities with a Z coordinate; the tools report how many were used
and where IDW extrapolated beyond them.
"""

import pywintypes

import cad_engine
from cad_engine import _retry_com, com_initialized, get_active_document, get_connected_app, get_drawing_identity, point_variant
from core import session
from core.errors import CadStateError, VerificationError
from core.evidence import validate_limit
from domain import civil, units
from tools._common import as_list, dxf_type, model_space, point3, read
from tools._common import get_entity as lookup_entity
from tools.layers import apply_layer_to_entity, get_or_create_layer
from utils import geometry
from utils.validation import MAX_CIVIL_PLACE_POINTS, MAX_CIVIL_PROFILE_SAMPLES, MAX_CIVIL_QUERY_POINTS

DEFAULT_MAX_ENTITIES = 20000


def _open_read_only():
    app = get_connected_app()
    return cad_engine.get_active_document(app, for_write=False)


def _bulges(entity) -> tuple[int, bool]:
    """(number of vertices with a non-zero bulge, whether it could be read).
    Only lightweight polylines carry bulges."""
    try:
        total = _retry_com(lambda: entity.NumberOfVertices)
        count = sum(1 for i in range(total) if _retry_com(lambda i=i: entity.GetBulge(i)))
        return count, True
    except (pywintypes.com_error, AttributeError, TypeError):
        return 0, False


def _alignment(doc, handle: str, label: str = "alignment") -> dict:
    """Vertex list, closed flag and metadata of a LINE or polyline used as a
    centreline. Anything else refuses with E_UNSUPPORTED_ENTITY."""
    handle = geometry.validate_handle(handle)
    entity = lookup_entity(doc, handle)
    object_name = read(entity, "ObjectName", "?")
    kind = dxf_type(object_name)
    if object_name == "AcDbLine":
        points = [point3(read(entity, "StartPoint")), point3(read(entity, "EndPoint"))]
        closed = False
    elif object_name in ("AcDbPolyline", "AcDb2dPolyline", "AcDb3dPolyline"):
        coords = [float(c) for c in as_list(read(entity, "Coordinates"))]
        step = 2 if object_name == "AcDbPolyline" else 3
        points = [[*coords[i:i + step], *([0.0] * (3 - step))] for i in range(0, len(coords) - step + 1, step)]
        closed = bool(read(entity, "Closed", False))
    else:
        raise CadStateError(
            f"{label} {handle} is a {kind} entity; stationing needs a LINE or a polyline "
            "(LWPOLYLINE, POLYLINE or 3D polyline).",
            code="E_UNSUPPORTED_ENTITY",
            details={"handle": handle, "type": kind},
        )
    if len(points) < 2 or any(p is None for p in points):
        raise CadStateError(f"{label} {handle} has fewer than 2 usable vertices.", code="E_UNSUPPORTED_ENTITY",
                            details={"handle": handle, "type": kind})
    if object_name == "AcDbPolyline":
        bulges, checked = _bulges(entity)
        if bulges or not checked:
            session.add_notice("alignment_arc_bulges_as_chords", handle=handle, bulge_vertices=bulges,
                               checked=checked)
    return {
        "handle": handle,
        "type": kind,
        "closed": closed,
        "points": points,
        "length": civil.alignment_length(points, closed=closed),
    }


def _point_samples(space, layer: str | None, max_entities: int) -> dict:
    """POINT entities (with Z) from ModelSpace, optionally one layer."""
    wanted = layer.lower() if layer else None
    samples, layers_seen = [], []
    count = _retry_com(lambda: space.Count)
    for index in range(min(count, max_entities)):
        try:
            entity = _retry_com(lambda index=index: space.Item(index))
        except Exception:  # an entity AutoCAD refuses to hand out is skipped, not fatal
            continue
        if read(entity, "ObjectName") != "AcDbPoint":
            continue
        entity_layer = read(entity, "Layer", "0")
        if wanted is not None and str(entity_layer).lower() != wanted:
            continue
        position = point3(read(entity, "Coordinates"))
        if position is None:
            continue
        samples.append(position)
        if str(entity_layer) not in layers_seen:
            layers_seen.append(str(entity_layer))
    return {"samples": samples, "scanned_entities": min(count, max_entities), "truncated": count > max_entities,
            "layers_seen": layers_seen}


def alignment_station(alignment: str, points, start_station: float = 0.0) -> dict:
    """Station and offset of each query point on the alignment (handle of a
    LINE or polyline). Read-only."""
    if not isinstance(points, (list, tuple)) or not points:
        raise geometry.ValidationError("points must be a non-empty list of [x, y] or [x, y, z] points")
    if len(points) > MAX_CIVIL_QUERY_POINTS:
        raise geometry.ValidationError(f"points has {len(points)} entries; the limit is {MAX_CIVIL_QUERY_POINTS}")
    wanted = [geometry.validate_point_2d_or_3d(p, f"points[{i}]") for i, p in enumerate(points)]
    start_station = geometry.validate_number(start_station, "start_station")

    with com_initialized():
        doc = _open_read_only()
        data = _alignment(doc, alignment)
        rows = []
        for point in wanted:
            result = civil.station_offset(data["points"], point, closed=data["closed"], start_station=start_station)
            rows.append({
                "point": list(point),
                "station": result["station"],
                "offset": result["offset"],
                "closest_point": result["closest_point"],
                "plan_distance": result["plan_distance"],
                "z_difference": result["z_difference"],
                "segment_index": result["segment_index"],
            })
        identity = get_drawing_identity(doc)
        length = data["length"]
        return {
            "status": "ok",
            "drawing_identity": identity.identity,
            "alignment": {"handle": data["handle"], "type": data["type"], "closed": data["closed"],
                          "vertex_count": len(data["points"]), "length": length,
                          "start_station": start_station, "end_station": start_station + length},
            "points": rows,
            "message": f"{len(rows)} point(s) queried against a {length:.3f}-unit alignment.",
        }


def station_point(alignment: str, stations, offset: float = 0.0, start_station: float = 0.0) -> dict:
    """Coordinates at each station (and one perpendicular offset) on the
    alignment. Read-only."""
    if not isinstance(stations, (list, tuple)) or not stations:
        raise geometry.ValidationError("stations must be a non-empty list of station numbers")
    if len(stations) > MAX_CIVIL_QUERY_POINTS:
        raise geometry.ValidationError(f"stations has {len(stations)} entries; the limit is {MAX_CIVIL_QUERY_POINTS}")
    wanted = [geometry.validate_number(s, f"stations[{i}]") for i, s in enumerate(stations)]
    offset = geometry.validate_number(offset, "offset")
    start_station = geometry.validate_number(start_station, "start_station")

    with com_initialized():
        doc = _open_read_only()
        data = _alignment(doc, alignment)
        rows = []
        for station in wanted:
            result = civil.point_at_station(data["points"], station, offset=offset, closed=data["closed"],
                                            start_station=start_station)
            rows.append({
                "station": result["station"],
                "offset": result["offset"],
                "point": result["point"],
                "tangent_angle_degrees": result["tangent_angle_degrees"],
                "segment_index": result["segment_index"],
                "clamped": result["clamped"],
            })
        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "drawing_identity": identity.identity,
            "alignment": {"handle": data["handle"], "type": data["type"], "closed": data["closed"],
                          "length": data["length"], "start_station": start_station,
                          "end_station": start_station + data["length"]},
            "stations": rows,
            "clamped_count": sum(1 for row in rows if row["clamped"]),
            "message": f"{len(rows)} station(s) computed on a {data['length']:.3f}-unit alignment.",
        }


def ground_profile(alignment: str, interval: float, layer: str | None = None, offset: float = 0.0,
                   method: str = "idw", neighbours: int = 8, start_station: float = 0.0,
                   max_entities: int = DEFAULT_MAX_ENTITIES) -> dict:
    """Ground levels sampled at stations along the alignment from POINT
    entities (spot levels) on `layer` (all layers when None). Read-only."""
    interval = geometry.validate_positive(interval, "interval")
    offset = geometry.validate_number(offset, "offset")
    start_station = geometry.validate_number(start_station, "start_station")
    if layer is not None:
        layer = geometry.validate_layer_name(layer)
    max_entities = validate_limit(max_entities, default=DEFAULT_MAX_ENTITIES, maximum=500000, label="max_entities")

    with com_initialized():
        doc = _open_read_only()
        data = _alignment(doc, alignment)
        series = civil.station_series(start_station, interval, start_station + data["length"],
                                      max_rows=MAX_CIVIL_PROFILE_SAMPLES)
        stations, truncated = series["stations"], series["truncated"]
        places = []
        for station in stations:
            at = civil.point_at_station(data["points"], station, offset=offset, closed=data["closed"],
                                        start_station=start_station)
            places.append((at["station"], at["point"][0], at["point"][1]))
        found = _point_samples(model_space(doc), layer, max_entities)
        rows = civil.sample_profile(places, found["samples"], method=method, neighbours=neighbours)
        elevations = [row["elevation"] for row in rows if row["elevation"] is not None]
        identity = get_drawing_identity(doc)
        result = {
            "status": "ok",
            "drawing_identity": identity.identity,
            "alignment": {"handle": data["handle"], "type": data["type"], "closed": data["closed"],
                          "length": data["length"], "start_station": start_station,
                          "end_station": start_station + data["length"]},
            "interval": interval,
            "offset": offset,
            "spot_levels": {"count": len(found["samples"]), "layer": layer,
                            "layers_seen": found["layers_seen"] if layer is None else None,
                            "scanned_entities": found["scanned_entities"], "scan_truncated": found["truncated"]},
            "stations": rows,
            "rows_truncated": truncated,
            "missing_elevations": len(rows) - len(elevations),
            "elevation_min": min(elevations) if elevations else None,
            "elevation_max": max(elevations) if elevations else None,
        }
        if not found["samples"]:
            result["message"] = ("No POINT entities with a Z were found"
                                 + (f" on layer {layer!r}." if layer else " in ModelSpace.")
                                 + " Every station reports elevation null.")
        else:
            result["message"] = (f"{len(rows)} station(s) sampled from {len(found['samples'])} spot level(s); "
                                 f"{result['missing_elevations']} without a value.")
        return result


def surface_volumes(existing_layer: str, design_layer: str, cell_size: float, method: str = "idw",
                    neighbours: int = 8, max_entities: int = DEFAULT_MAX_ENTITIES) -> dict:
    """Grid-method cut and fill between two Z-bearing POINT layers. Read-only."""
    existing_layer = geometry.validate_layer_name(existing_layer, "existing_layer")
    design_layer = geometry.validate_layer_name(design_layer, "design_layer")
    max_entities = validate_limit(max_entities, default=DEFAULT_MAX_ENTITIES, maximum=500000, label="max_entities")

    with com_initialized():
        doc = _open_read_only()
        space = model_space(doc)
        ground = _point_samples(space, existing_layer, max_entities)
        design = _point_samples(space, design_layer, max_entities)
        for samples, name in ((ground, existing_layer), (design, design_layer)):
            if not samples["samples"]:
                raise CadStateError(
                    f"No POINT entities with a Z were found on layer {name!r}.",
                    code="E_ENTITY_NOT_FOUND",
                    details={"layer": name},
                    recommended_action=("add POINT entities with Z to that layer, or pass the layer "
                                        "that holds the spot levels"),
                )
        result = civil.grid_volumes(ground["samples"], design["samples"], cell_size, method=method,
                                    neighbours=neighbours)
        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "drawing_identity": identity.identity,
            "existing_layer": existing_layer,
            "design_layer": design_layer,
            **result,
            "spot_levels": {
                "existing": {"count": len(ground["samples"]), "scan_truncated": ground["truncated"]},
                "design": {"count": len(design["samples"]), "scan_truncated": design["truncated"]},
            },
            "message": (f"Grid method over {result['cells_total']} cell(s) of {result['cell_size']} unit(s): "
                        f"cut {result['cut_volume']:.3f}, fill {result['fill_volume']:.3f} "
                        f"(net {result['net_volume']:.3f}, positive = surplus fill). "
                        "A drafting aid from the spot levels given, not a survey report."),
        }


def pipe_clearance(first: str, second: str, first_diameter: float | None = None,
                   second_diameter: float | None = None) -> dict:
    """Minimum 3D distance and plan crossings between two pipe axis entities
    (LINE or polyline). Read-only."""
    with com_initialized():
        doc = _open_read_only()
        first_data = _alignment(doc, first, label="first pipe")
        second_data = _alignment(doc, second, label="second pipe")
        result = civil.pipe_clearance(first_data["points"], second_data["points"],
                                      first_diameter=first_diameter, second_diameter=second_diameter)
        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "drawing_identity": identity.identity,
            "first_pipe": {"handle": first_data["handle"], "type": first_data["type"], "vertex_count": len(first_data["points"])},
            "second_pipe": {"handle": second_data["handle"], "type": second_data["type"], "vertex_count": len(second_data["points"])},
            **result,
            "message": (f"Closest approach {result['minimum_distance']:.3f} unit(s) over "
                        f"{len(result['crossings'])} plan crossing(s)."),
        }


def place_points(points, layer: str = "C-POINT", label: bool = True, text_height: float | None = None,
                 start_number: int = 1) -> dict:
    """Place numbered point markers (POINT entities, optionally with a
    number/level label) at the given coordinates. Writes."""
    if not isinstance(points, (list, tuple)) or not points:
        raise geometry.ValidationError("points must be a non-empty list of [x, y] or [x, y, z] points")
    if len(points) > MAX_CIVIL_PLACE_POINTS:
        raise geometry.ValidationError(f"points has {len(points)} entries; the limit is {MAX_CIVIL_PLACE_POINTS}")
    wanted = [geometry.validate_point_2d_or_3d(p, f"points[{i}]") for i, p in enumerate(points)]
    layer = geometry.validate_layer_name(layer)
    if isinstance(start_number, bool) or not isinstance(start_number, int) or start_number < 0:
        raise geometry.ValidationError(f"start_number must be a non-negative integer, got {start_number!r}")
    if text_height is not None:
        text_height = geometry.validate_positive(text_height, "text_height")

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app, for_write=True)
        space = model_space(doc)
        if text_height is None:
            code = cad_engine.read_insunits(doc)
            if code is None:
                code = 1  # unreadable INSUNITS: V0.2.x behaviour (inches)
            text_height = units.defaults_for(code)["text_height"]
        get_or_create_layer(doc, layer)
        count_before = _retry_com(lambda: space.Count)

        placed = []
        for index, point in enumerate(wanted):
            number = start_number + index
            marker = _retry_com(lambda point=point: space.AddPoint(point_variant(tuple(point))))
            apply_layer_to_entity(doc, marker, layer)
            row = {"number": number, "point": list(point), "handle": _retry_com(lambda marker=marker: marker.Handle)}
            if label:
                text = str(number) if point[2] == 0 else f"{number} Z={point[2]:g}"
                anchor = (point[0] + text_height * 0.5, point[1] + text_height * 0.5, point[2])
                tag = _retry_com(lambda text=text, anchor=anchor: space.AddText(text, point_variant(anchor), text_height))
                apply_layer_to_entity(doc, tag, layer)
                row["label_handle"] = _retry_com(lambda tag=tag: tag.Handle)
            placed.append(row)

        expected = len(placed) * (2 if label else 1)
        count_after = _retry_com(lambda: space.Count)
        if count_after != count_before + expected:
            raise VerificationError(
                f"Point placement could not be verified: expected ModelSpace count {count_before + expected}, "
                f"got {count_after}.")
        for row in placed:
            marker = lookup_entity(doc, row["handle"])
            if read(marker, "ObjectName") != "AcDbPoint":
                raise VerificationError(f"Entity {row['handle']} is not a POINT after creation.")
            if label and read(lookup_entity(doc, row["label_handle"]), "ObjectName") != "AcDbText":
                raise VerificationError(f"Entity {row['label_handle']} is not a TEXT label after creation.")
        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "drawing_identity": identity.identity,
            "layer": layer,
            "points": placed,
            "count": len(placed),
            "labelled": bool(label),
            "text_height": text_height,
            "verified": True,
            "verification": "modelspace_count_plus_n_and_object_names",
            "message": (f"Placed {len(placed)} point marker(s) on layer {layer!r}"
                        + (f" with number/level labels at height {text_height}." if label else ".")),
        }
