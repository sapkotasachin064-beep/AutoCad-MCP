"""Block definitions, block references and attributes over COM (V0.3.0).

insert_block checks the block exists and that every requested attribute tag
is defined (ATTDEF) before inserting anything, so a typo cannot leave a
half-filled block behind. Attribute values are read back.
"""

import pywintypes

from cad_engine import _retry_com, com_initialized, get_active_document, get_connected_app, get_drawing_identity
from core.errors import CadStateError, VerificationError
from tools._common import as_list, deg_to_rad, get_entity, model_space, point, read, verify_count_and_type
from tools.layers import apply_layer_to_entity
from utils import geometry

MAX_ATTDEF_SCAN = 5000


def _definitions(doc, include_anonymous: bool):
    blocks = doc.Blocks
    for i in range(_retry_com(lambda: blocks.Count)):
        block = _retry_com(lambda i=i: blocks.Item(i))
        if read(block, "IsLayout", False):
            continue
        name = read(block, "Name", "")
        if not include_anonymous and name.startswith("*"):
            continue
        yield block, name


def _attdef_tags(block) -> list[str]:
    tags = []
    count = min(_retry_com(lambda: block.Count), MAX_ATTDEF_SCAN)
    for i in range(count):
        item = _retry_com(lambda i=i: block.Item(i))
        if read(item, "ObjectName") == "AcDbAttributeDefinition":
            tags.append(read(item, "TagString"))
    return tags


def _block(doc, name: str):
    try:
        return _retry_com(lambda: doc.Blocks.Item(name))
    except pywintypes.com_error as exc:
        raise CadStateError(f"Block {name!r} is not defined in this drawing.", code="E_BLOCK_NOT_FOUND",
                            details={"block": name}) from exc


def _attributes(reference) -> list:
    if not read(reference, "HasAttributes", False):
        return []
    try:
        return as_list(_retry_com(lambda: reference.GetAttributes()))
    except pywintypes.com_error:
        return []


def list_blocks(include_anonymous: bool = False) -> dict:
    with com_initialized():
        doc = get_active_document(get_connected_app(), for_write=False)
        rows = []
        for block, name in _definitions(doc, include_anonymous):
            is_xref = bool(read(block, "IsXRef", False))
            rows.append({
                "name": name,
                "entity_count": read(block, "Count"),
                "is_xref": is_xref,
                "xref_path": read(block, "Path") if is_xref else None,
                "attribute_tags": [] if is_xref else _attdef_tags(block),
            })
        rows.sort(key=lambda r: r["name"].lower())
        return {"status": "ok", "count": len(rows), "blocks": rows,
                "drawing_identity": get_drawing_identity(doc).identity}


def insert_block(name: str, insertion_point, scale: float = 1.0, rotation_degrees: float = 0.0,
                 layer: str | None = None, attributes: dict | None = None) -> dict:
    if not isinstance(name, str) or not name.strip():
        raise geometry.ValidationError("name must be a non-empty block name")
    p = geometry.validate_point_2d_or_3d(insertion_point, "insertion_point")
    scale = geometry.validate_positive(scale, "scale")
    rotation = geometry.validate_angle_degrees(rotation_degrees, "rotation_degrees")
    if layer is not None:
        layer = geometry.validate_layer_name(layer)
    if attributes is not None:
        if not isinstance(attributes, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                       for k, v in attributes.items()):
            raise geometry.ValidationError("attributes must map tag strings to value strings")
    with com_initialized():
        doc = get_active_document(get_connected_app())
        block = _block(doc, name.strip())
        if attributes:
            defined = {t.upper() for t in _attdef_tags(block)}
            unknown = sorted(t for t in attributes if t.upper() not in defined)
            if unknown:
                raise geometry.ValidationError(
                    f"block {name!r} defines no attribute tag(s) {unknown}; defined: {sorted(defined)}")
        space = model_space(doc)
        count_before = _retry_com(lambda: space.Count)
        try:
            reference = _retry_com(lambda: space.InsertBlock(point(p), name.strip(), scale, scale, scale,
                                                             deg_to_rad(rotation)))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to insert block {name!r}: {exc}") from exc
        verify_count_and_type(space, count_before, reference, "AcDbBlockReference")
        if layer is not None:
            apply_layer_to_entity(doc, reference, layer)
        values = {}
        if attributes:
            wanted = {k.upper(): v for k, v in attributes.items()}
            for attribute in _attributes(reference):
                tag = str(read(attribute, "TagString", "")).upper()
                if tag in wanted:
                    _retry_com(lambda a=attribute, v=wanted[tag]: setattr(a, "TextString", v))
            values = {str(read(a, "TagString")): read(a, "TextString") for a in _attributes(reference)}
            wrong = {t: values.get(t) for t, v in wanted.items()
                     if {k.upper(): val for k, val in values.items()}.get(t) != v}
            if wrong:
                raise VerificationError(f"Block inserted but attributes read back differently: {wrong}",
                                        details={"handle": _retry_com(lambda: reference.Handle)})
        return {
            "status": "ok",
            "handle": _retry_com(lambda: reference.Handle),
            "block": read(reference, "EffectiveName") or name,
            "insertion_point": p, "scale": scale, "rotation_degrees": rotation,
            "layer": read(reference, "Layer"),
            "attributes": values,
            "verified": True,
            "verification": "modelspace_count_object_name_and_attributes_read_back",
            "drawing_identity": get_drawing_identity(doc).identity,
            "message": f"Inserted block {name!r}.",
        }


def get_block_attributes(handle: str) -> dict:
    handle = geometry.validate_handle(handle)
    with com_initialized():
        doc = get_active_document(get_connected_app(), for_write=False)
        reference = get_entity(doc, handle)
        if read(reference, "ObjectName") != "AcDbBlockReference":
            raise geometry.ValidationError(f"{handle} is not a block reference")
        rows = [{"tag": read(a, "TagString"), "value": read(a, "TextString"), "handle": read(a, "Handle")}
                for a in _attributes(reference)]
        return {"status": "ok", "handle": handle, "block": read(reference, "EffectiveName") or read(reference, "Name"),
                "attributes": rows, "drawing_identity": get_drawing_identity(doc).identity}


def set_block_attributes(handle: str, values: dict) -> dict:
    handle = geometry.validate_handle(handle)
    if not isinstance(values, dict) or not values or not all(isinstance(k, str) and isinstance(v, str)
                                                             for k, v in values.items()):
        raise geometry.ValidationError("values must be a non-empty map of tag -> text")
    with com_initialized():
        doc = get_active_document(get_connected_app())
        reference = get_entity(doc, handle)
        if read(reference, "ObjectName") != "AcDbBlockReference":
            raise geometry.ValidationError(f"{handle} is not a block reference")
        attributes = _attributes(reference)
        by_tag = {str(read(a, "TagString", "")).upper(): a for a in attributes}
        unknown = sorted(t for t in values if t.upper() not in by_tag)
        if unknown:
            raise geometry.ValidationError(f"no attribute tag(s) {unknown} on this block; tags: {sorted(by_tag)}")
        before = {t: read(a, "TextString") for t, a in by_tag.items()}
        for tag, value in values.items():
            _retry_com(lambda a=by_tag[tag.upper()], v=value: setattr(a, "TextString", v))
        after = {t: read(a, "TextString") for t, a in by_tag.items()}
        mismatched = {t: after[t.upper()] for t, v in values.items() if after[t.upper()] != v}
        return {
            "status": "ok", "handle": handle, "before": before, "after": after,
            "verified": not mismatched, "verification": "attribute_text_read_back", "mismatched": mismatched,
            "drawing_identity": get_drawing_identity(doc).identity,
            "message": f"Updated {len(values)} attribute(s) on {handle}.",
        }
