"""Drawing analysis tools: scan_all_entities, count_text_patterns.

scan_all_entities only looks at top-level ModelSpace entities (lines,
circles, 3D/lightweight polylines, text/mtext) -- it does not recurse into
block references or PaperSpace. That is a real scope limit, documented here
and in the README, not something papered over.
"""

import re
from collections import Counter

import pywintypes

import db
from cad_engine import _retry_com, com_initialized, get_active_document, get_connected_app, get_drawing_identity
from core.evidence import validate_limit
from utils import geometry
from utils.constants import TEXT_OBJECT_NAMES, get_db_path


def _read_properties(entity, object_name: str) -> dict | None:
    """Best-effort property extraction. Returns None if even the entity's
    own type-specific properties can't be read (treated by the caller as an
    inaccessible entity, not a fatal scan error)."""
    try:
        if object_name == "AcDbLine":
            start = entity.StartPoint
            end = entity.EndPoint
            return {"start_point": [start[0], start[1], start[2]], "end_point": [end[0], end[1], end[2]]}
        if object_name == "AcDbCircle":
            center = entity.Center
            return {"center": [center[0], center[1], center[2]], "radius": entity.Radius}
        if object_name in ("AcDb3dPolyline", "AcDbPolyline"):
            coords = list(entity.Coordinates)
            divisor = 3 if object_name == "AcDb3dPolyline" else 2
            vertex_count = len(coords) // divisor if divisor else 0
            return {"vertex_count": vertex_count, "closed": bool(entity.Closed)}
        if object_name in TEXT_OBJECT_NAMES:
            text = entity.TextString
            point = entity.InsertionPoint
            return {
                "text": text,
                "insertion_point": [point[0], point[1], point[2]],
                "height": entity.Height,
            }
    except pywintypes.com_error:
        return None
    return {}


def scan_all_entities() -> dict:
    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app, for_write=False)
        model_space = _retry_com(lambda: doc.ModelSpace)
        count = _retry_com(lambda: model_space.Count)

        entities = []
        skipped_count = 0
        for i in range(count):
            try:
                entity = _retry_com(lambda: model_space.Item(i))
                object_name = _retry_com(lambda: entity.ObjectName)
                handle = _retry_com(lambda: entity.Handle)
                layer = _retry_com(lambda: entity.Layer)
            except pywintypes.com_error:
                skipped_count += 1
                continue

            properties = _read_properties(entity, object_name)
            if properties is None:
                skipped_count += 1
                continue

            entities.append(
                {"handle": handle, "object_name": object_name, "layer": layer, "properties": properties}
            )

        identity = get_drawing_identity(doc)
        db_path = get_db_path()
        with db.connection(db_path) as conn:
            drawing_id = db.upsert_drawing(conn, identity.identity, identity.name, identity.path, identity.saved)
            db.replace_drawing_entities(conn, drawing_id, entities)

        type_counts = dict(Counter(e["object_name"] for e in entities))
        return {
            "status": "ok",
            "drawing_identity": identity.identity,
            "scanned_count": len(entities),
            "skipped_count": skipped_count,
            "entity_type_counts": type_counts,
            "db_path": db_path,
            "scope_note": "top-level ModelSpace entities only; block references and PaperSpace are not scanned.",
            "message": f"Scanned {len(entities)} entities ({skipped_count} inaccessible/skipped) into {db_path}.",
        }


def count_text_patterns(pattern: str, use_regex: bool = False, limit: int = 500) -> dict:
    """Count every matching TEXT/MTEXT entity; list at most `limit` of them
    (match_count is always the full count, `truncated` says if the list was
    cut)."""
    pattern = geometry.validate_text(pattern, "pattern")
    if not pattern:
        raise geometry.ValidationError("pattern must not be empty")
    limit = validate_limit(limit, default=500, maximum=10000)
    compiled = None
    if use_regex:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise geometry.ValidationError(f"pattern is not a valid regex: {exc}") from exc

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app, for_write=False)
        model_space = _retry_com(lambda: doc.ModelSpace)
        count = _retry_com(lambda: model_space.Count)

        matches = []
        for i in range(count):
            try:
                entity = _retry_com(lambda: model_space.Item(i))
                object_name = _retry_com(lambda: entity.ObjectName)
            except pywintypes.com_error:
                continue
            if object_name not in TEXT_OBJECT_NAMES:
                continue
            try:
                text = _retry_com(lambda: entity.TextString)
                layer = _retry_com(lambda: entity.Layer)
                handle = _retry_com(lambda: entity.Handle)
            except pywintypes.com_error:
                continue

            is_match = bool(compiled.search(text)) if compiled else (pattern in text)
            if is_match:
                matches.append({"handle": handle, "text": text, "layer": layer})

        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "pattern": pattern,
            "use_regex": use_regex,
            "match_count": len(matches),
            "matches": matches[:limit],
            "truncated": len(matches) > limit,
            "drawing_identity": identity.identity,
            "message": f"{len(matches)} text entity(ies) match {pattern!r} ({'regex' if use_regex else 'literal substring'}).",
        }
