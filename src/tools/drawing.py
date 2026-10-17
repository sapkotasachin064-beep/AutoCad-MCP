"""Entity creation over COM: drawing primitives, layers and blocks.

Merged from primitives.py, layers.py and blocks.py in the
minimal-architecture refactor. Every public function runs on the COM thread
via backends/com.py and reads its own effect back for the verification block.
"""


# ======= primitives.py =======
import os
from datetime import datetime

import pywintypes

from backends.com_engine import _retry_com, com_initialized, flat_variant, get_active_document, get_connected_app, get_drawing_identity, point_variant
from core import session
from core.errors import CadStateError, VerificationError
from core.paths import input_path
from utils import geometry
from utils.constants import get_output_dir


def _model_space(doc):
    return _retry_com(lambda: doc.ModelSpace)


def _verify_added(model_space, count_before: int, expected_object_name: str, entity):
    count_after = _retry_com(lambda: model_space.Count)
    object_name = _retry_com(lambda: entity.ObjectName)
    if count_after != count_before + 1 or object_name != expected_object_name:
        raise VerificationError(
            f"Entity creation could not be verified: expected ModelSpace count "
            f"{count_before + 1} and ObjectName {expected_object_name!r}, got "
            f"count {count_after} and ObjectName {object_name!r}."
        )


def _validate_template(template):
    """A bare file name ("acad.dwt") is passed through for AutoCAD to find on
    its own template path; anything with a folder must be an existing .dwt."""
    if template is None:
        return None
    if not isinstance(template, str) or not template.strip():
        raise geometry.ValidationError(f"template must be a non-empty string, got {template!r}")
    template = template.strip()
    if os.path.basename(template) == template:
        if not template.lower().endswith(".dwt"):
            raise geometry.ValidationError(f"template must be a .dwt file, got {template!r}")
        return template
    return str(input_path(template, suffixes=(".dwt",)))


def create_new_drawing(template: str | None = None, pin: bool = False) -> dict:
    """Documents.Add(), never touching disk. While a document pin is set the
    new drawing would become active and break the pinned job, so this refuses
    unless pin=True, which moves the pin to the new drawing."""
    template = _validate_template(template)
    previous_pin = session.pinned_document()
    if previous_pin is not None and not pin:
        raise CadStateError(
            f"This session is pinned to {previous_pin!r}; creating a drawing would switch the active "
            "drawing away from it. Pass pin=true to move the pin to the new drawing, or unpin first.",
            code="E_DOCUMENT_PINNED",
            details={"pinned_document": previous_pin},
        )

    with com_initialized():
        app = get_connected_app()
        try:
            doc = _retry_com(lambda: app.Documents.Add(template)) if template else _retry_com(
                lambda: app.Documents.Add()
            )
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create new drawing: {exc}") from exc

        active = _retry_com(lambda: app.ActiveDocument)
        # AutoCAD is often still busy right after Documents.Add; property reads
        # need the same busy-retry (seen live on 2024: "Call was rejected by callee").
        new_name = _retry_com(lambda: doc.Name)
        active_name = _retry_com(lambda: active.Name)
        if active_name != new_name:
            raise RuntimeError(
                f"New drawing {new_name!r} was created but is not the active document "
                f"(active is {active_name!r}); refusing to proceed against the wrong drawing."
            )

        identity = get_drawing_identity(doc)
        if pin:
            session.pin_document(identity.identity)
        return {
            "status": "ok",
            "drawing_name": new_name,
            "drawing_identity": identity.identity,
            "saved": identity.saved,
            "pinned": bool(pin),
            "previous_pin": previous_pin,
            "verified": True,
            "verification": "new_document_is_active",
            "message": f"Created new drawing {new_name!r}." + (" Pinned." if pin else ""),
        }


def draw_line(start_point, end_point, layer: str | None = None) -> dict:
    start = geometry.validate_point_2d_or_3d(start_point, "start_point")
    end = geometry.validate_point_2d_or_3d(end_point, "end_point")
    if layer is not None:
        layer = geometry.validate_layer_name(layer)

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app)
        model_space = _model_space(doc)
        count_before = _retry_com(lambda: model_space.Count)

        try:
            line = _retry_com(lambda: model_space.AddLine(point_variant(start), point_variant(end)))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create line: {exc}") from exc

        _verify_added(model_space, count_before, "AcDbLine", line)
        if layer is not None:
            apply_layer_to_entity(doc, line, layer)

        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "handle": line.Handle,
            "start_point": start,
            "end_point": end,
            "layer": _retry_com(lambda: line.Layer),
            "verified": True,
            "verification": "modelspace_count_plus_one_and_object_name",
            "drawing_identity": identity.identity,
            "message": f"Created line {line.Handle} from {start} to {end}.",
        }


def draw_polyline(points, closed: bool = False, layer: str | None = None) -> dict:
    validated_points = geometry.validate_points(points, "points")
    if layer is not None:
        layer = geometry.validate_layer_name(layer)

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app)
        model_space = _model_space(doc)
        count_before = _retry_com(lambda: model_space.Count)

        flat = [coord for point in validated_points for coord in point]
        try:
            pline = _retry_com(lambda: model_space.Add3DPoly(flat_variant(flat)))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create polyline: {exc}") from exc

        if closed:
            try:
                _retry_com(lambda: setattr(pline, "Closed", True))
            except pywintypes.com_error as exc:
                raise RuntimeError(f"Polyline created but failed to close it: {exc}") from exc

        _verify_added(model_space, count_before, "AcDb3dPolyline", pline)
        if layer is not None:
            apply_layer_to_entity(doc, pline, layer)

        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "handle": pline.Handle,
            "points": validated_points,
            "closed": closed,
            "layer": _retry_com(lambda: pline.Layer),
            "verified": True,
            "verification": "modelspace_count_plus_one_and_object_name",
            "drawing_identity": identity.identity,
            "message": f"Created polyline {pline.Handle} with {len(validated_points)} points.",
        }


def draw_rectangle(
    corner1=None,
    corner2=None,
    base_point=None,
    width: float | None = None,
    height: float | None = None,
    layer: str | None = None,
) -> dict:
    by_corners = corner1 is not None and corner2 is not None
    by_size = base_point is not None and width is not None and height is not None
    if by_corners == by_size:
        raise geometry.ValidationError(
            "draw_rectangle needs exactly one of: (corner1 and corner2), or "
            "(base_point and width and height)"
        )

    if by_corners:
        c1 = geometry.validate_point_2d_or_3d(corner1, "corner1")
        c2 = geometry.validate_point_2d_or_3d(corner2, "corner2")
        if c1[2] != c2[2]:
            raise geometry.ValidationError(
                f"corner1 and corner2 must lie in the same z-plane, got z={c1[2]} and z={c2[2]}"
            )
        x1, y1, z = c1
        x2, y2, _ = c2
    else:
        base = geometry.validate_point_2d_or_3d(base_point, "base_point")
        width = geometry.validate_positive(width, "width")
        height = geometry.validate_positive(height, "height")
        x1, y1, z = base
        x2, y2 = x1 + width, y1 + height

    rect_points = [(x1, y1, z), (x2, y1, z), (x2, y2, z), (x1, y2, z)]
    return draw_polyline(rect_points, closed=True, layer=layer)


def draw_circle(center, radius, layer: str | None = None) -> dict:
    center_point = geometry.validate_point_2d_or_3d(center, "center")
    radius = geometry.validate_radius(radius)
    if layer is not None:
        layer = geometry.validate_layer_name(layer)

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app)
        model_space = _model_space(doc)
        count_before = _retry_com(lambda: model_space.Count)

        try:
            circle = _retry_com(lambda: model_space.AddCircle(point_variant(center_point), radius))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create circle: {exc}") from exc

        _verify_added(model_space, count_before, "AcDbCircle", circle)
        if layer is not None:
            apply_layer_to_entity(doc, circle, layer)

        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "handle": circle.Handle,
            "center": center_point,
            "radius": radius,
            "layer": _retry_com(lambda: circle.Layer),
            "verified": True,
            "verification": "modelspace_count_plus_one_and_object_name",
            "drawing_identity": identity.identity,
            "message": f"Created circle {circle.Handle} at {center_point} with radius {radius}.",
        }


def draw_text(
    text: str,
    insertion_point,
    height: float,
    rotation_degrees: float = 0.0,
    layer: str | None = None,
) -> dict:
    requested = geometry.validate_text(text)
    text = geometry.clean_label_text(requested)
    point = geometry.validate_point_2d_or_3d(insertion_point, "insertion_point")
    height = geometry.validate_positive(height, "height")
    rotation_degrees = geometry.validate_angle_degrees(rotation_degrees, "rotation_degrees")
    if layer is not None:
        layer = geometry.validate_layer_name(layer)

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app)
        model_space = _model_space(doc)
        count_before = _retry_com(lambda: model_space.Count)

        try:
            text_obj = _retry_com(lambda: model_space.AddText(text, point_variant(point), height))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create text: {exc}") from exc

        if rotation_degrees:
            try:
                _retry_com(
                    lambda: setattr(text_obj, "Rotation", geometry.degrees_to_radians(rotation_degrees))
                )
            except pywintypes.com_error as exc:
                raise RuntimeError(f"Text created but failed to set rotation: {exc}") from exc

        _verify_added(model_space, count_before, "AcDbText", text_obj)
        if layer is not None:
            apply_layer_to_entity(doc, text_obj, layer)

        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "handle": text_obj.Handle,
            "text": text,
            **geometry.cleaned_note(requested, text),
            "insertion_point": point,
            "height": height,
            "rotation_degrees": rotation_degrees,
            "layer": _retry_com(lambda: text_obj.Layer),
            "verified": True,
            "verification": "modelspace_count_plus_one_and_object_name",
            "drawing_identity": identity.identity,
            "message": f"Created text {text_obj.Handle} at {point}.",
        }


# ======= V0.1.0 test fixture =======

_TEST_START_POINT = (0.0, 0.0, 0.0)
_TEST_END_POINT = (100.0, 100.0, 0.0)


def _unique_test_path(output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    while True:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        candidate = os.path.join(output_dir, f"mcp_test_{timestamp}.dwg")
        if not os.path.exists(candidate):
            return candidate


def create_test_drawing_with_line(output_dir: str | None = None) -> dict:
    with com_initialized():
        app = get_connected_app()
        output_dir = output_dir or get_output_dir()
        file_path = _unique_test_path(output_dir)

        try:
            doc = _retry_com(lambda: app.Documents.Add())
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create new drawing: {exc}") from exc

        active = _retry_com(lambda: app.ActiveDocument)
        if active.Name != doc.Name:
            raise RuntimeError(
                f"New drawing {doc.Name!r} was created but is not the active document "
                f"(active is {active.Name!r}); refusing to draw into the wrong drawing."
            )

        model_space = _retry_com(lambda: doc.ModelSpace)
        count_before = _retry_com(lambda: model_space.Count)

        try:
            line = _retry_com(
                lambda: model_space.AddLine(point_variant(_TEST_START_POINT), point_variant(_TEST_END_POINT))
            )
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create line entity: {exc}") from exc

        count_after = _retry_com(lambda: model_space.Count)
        if count_after != count_before + 1 or line.ObjectName != "AcDbLine":
            raise RuntimeError("Line entity was not created as expected in ModelSpace.")

        if os.path.exists(file_path):
            raise RuntimeError(f"Refusing to overwrite existing file: {file_path}")

        try:
            _retry_com(lambda: doc.SaveAs(file_path))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to save drawing to {file_path}: {exc}") from exc

        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            raise RuntimeError(f"Save reported success but file is missing or empty: {file_path}")

        return {
            "status": "ok",
            "file_path": file_path,
            "line_handle": line.Handle,
            "start_point": _TEST_START_POINT,
            "end_point": _TEST_END_POINT,
            "message": f"Drawing saved with 1 line entity at {file_path}",
        }


# ======= layers.py =======

from utils.constants import ARCHITECTURAL_LAYERS


def get_or_create_layer(doc, name: str):
    try:
        return _retry_com(lambda: doc.Layers.Item(name))
    except pywintypes.com_error:
        try:
            return _retry_com(lambda: doc.Layers.Add(name))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create layer {name!r}: {exc}") from exc


def ensure_linetype(doc, name: str) -> str:
    """Return the drawing's own spelling of linetype `name`, loading it from
    the standard library file (acad.lin for imperial drawings, acadiso.lin for
    metric, by MEASUREMENT) through the ActiveX Linetypes.Load member when it
    isn't loaded yet. The name is data to Load, never typed at the command
    line, so it cannot inject a command."""
    if not isinstance(name, str) or not name.strip() or any(c in name for c in '<>/\\":;?*|,=`\n\r\t'):
        raise geometry.ValidationError(f"invalid linetype name {name!r}")
    name = name.strip()
    linetypes = doc.Linetypes
    try:
        return _retry_com(lambda: linetypes.Item(name)).Name
    except pywintypes.com_error:
        pass
    try:
        metric = int(doc.GetVariable("MEASUREMENT")) == 1
    except (pywintypes.com_error, AttributeError, TypeError, ValueError):
        metric = False
    library = "acadiso.lin" if metric else "acad.lin"
    try:
        _retry_com(lambda: linetypes.Load(name, library))
        return _retry_com(lambda: linetypes.Item(name)).Name
    except pywintypes.com_error as exc:
        raise geometry.ValidationError(f"linetype {name!r} is not loaded and could not be loaded from {library}: {exc}") from exc


from utils.validation import LAYER_LINEWEIGHTS  # noqa: E402  (re-exported)


def set_layer_properties(
    name: str,
    on: bool | None = None,
    frozen: bool | None = None,
    locked: bool | None = None,
    color_index: int | None = None,
    linetype: str | None = None,
    lineweight: int | None = None,
    plottable: bool | None = None,
) -> dict:
    """Change only the properties given; reads every one back. The current
    layer cannot be frozen (AutoCAD refuses), so that is rejected up front."""
    name = geometry.validate_layer_name(name)
    if color_index is not None:
        color_index = geometry.validate_color_index(color_index, "color_index")
    if lineweight is not None and lineweight not in LAYER_LINEWEIGHTS:
        raise geometry.ValidationError(
            f"lineweight must be one of {sorted(LAYER_LINEWEIGHTS)} (hundredths of mm, -3 = Default)")
    for label, value in (("on", on), ("frozen", frozen), ("locked", locked), ("plottable", plottable)):
        if value is not None and not isinstance(value, bool):
            raise geometry.ValidationError(f"{label} must be true or false")
    if all(v is None for v in (on, frozen, locked, color_index, linetype, lineweight, plottable)):
        raise geometry.ValidationError("give at least one property to change")

    with com_initialized():
        doc = get_active_document(get_connected_app())
        try:
            layer = _retry_com(lambda: doc.Layers.Item(name))
        except pywintypes.com_error as exc:
            raise CadStateError(f"Layer {name!r} does not exist.", code="E_LAYER_NOT_FOUND",
                                details={"layer": name}) from exc
        current = _retry_com(lambda: doc.ActiveLayer.Name)
        if frozen and current.lower() == name.lower():
            raise geometry.ValidationError(f"{name!r} is the current layer, which AutoCAD cannot freeze")
        if linetype is not None:
            linetype = ensure_linetype(doc, linetype)
        wanted = {k: v for k, v in (("LayerOn", on), ("Freeze", frozen), ("Lock", locked), ("Color", color_index),
                                    ("Linetype", linetype), ("Lineweight", lineweight), ("Plottable", plottable))
                  if v is not None}
        before = {prop: _retry_com(lambda prop=prop: getattr(layer, prop)) for prop in wanted}
        for prop, value in wanted.items():
            try:
                _retry_com(lambda prop=prop, value=value: setattr(layer, prop, value))
            except pywintypes.com_error as exc:
                raise RuntimeError(f"Failed to set {prop} on layer {name!r}: {exc}") from exc
        after = {prop: _retry_com(lambda prop=prop: getattr(layer, prop)) for prop in wanted}
        mismatched = {p: after[p] for p, v in wanted.items() if str(after[p]).lower() != str(v).lower()}
        identity = get_drawing_identity(doc)
        return {
            "status": "ok",
            "layer_name": name,
            "before": before,
            "after": after,
            "verified": not mismatched,
            "verification": "layer_properties_read_back",
            "mismatched": mismatched,
            "drawing_identity": identity.identity,
            "message": f"Layer {name!r} updated: {', '.join(f'{k}={v}' for k, v in wanted.items())}.",
        }


def apply_layer_to_entity(doc, entity, name: str) -> None:
    get_or_create_layer(doc, name)
    try:
        _retry_com(lambda: setattr(entity, "Layer", name))
    except pywintypes.com_error as exc:
        raise RuntimeError(f"Failed to set entity layer to {name!r}: {exc}") from exc


def create_layer(name: str, color_index: int | None = None, linetype: str | None = None) -> dict:
    """Create the layer if it doesn't exist. Only color_index/linetype, when
    given, are changed on an existing layer; every other property (locked,
    frozen, on/off, plot style, ...) is left exactly as it was."""
    name = geometry.validate_layer_name(name)
    if color_index is not None:
        color_index = geometry.validate_color_index(color_index)

    with com_initialized():
        app = get_connected_app()
        doc = get_active_document(app)

        existed = True
        try:
            layer = _retry_com(lambda: doc.Layers.Item(name))
        except pywintypes.com_error:
            existed = False
            try:
                layer = _retry_com(lambda: doc.Layers.Add(name))
            except pywintypes.com_error as exc:
                raise RuntimeError(f"Failed to create layer {name!r}: {exc}") from exc

        if color_index is not None:
            try:
                _retry_com(lambda: setattr(layer, "Color", color_index))
            except pywintypes.com_error as exc:
                raise RuntimeError(f"Failed to set color on layer {name!r}: {exc}") from exc
        if linetype is not None:
            linetype = ensure_linetype(doc, linetype)  # V0.3.0: loads it from acad(iso).lin if needed
            try:
                _retry_com(lambda: setattr(layer, "Linetype", linetype))
            except pywintypes.com_error as exc:
                raise RuntimeError(f"Failed to set linetype on layer {name!r} (is it loaded?): {exc}") from exc

        applied_color = _retry_com(lambda: layer.Color)
        applied_linetype = _retry_com(lambda: layer.Linetype)
        identity = get_drawing_identity(doc)

        return {
            "status": "ok",
            "layer_name": name,
            "created": not existed,
            "color_index": applied_color,
            "linetype": applied_linetype,
            "verified": (color_index is None or applied_color == color_index)
            and (linetype is None or str(applied_linetype).lower() == linetype.lower()),
            "verification": "layer_properties_read_back",
            "drawing_identity": identity.identity,
            "message": f"Layer {name!r} {'created' if not existed else 'updated'}.",
        }


def ensure_layer(name: str, color_index: int | None = None, linetype: str | None = None) -> dict:
    """Same as create_layer, except a name matching the architectural layer
    standard (A-WALL, A-DOOR, A-GLAZ, A-ANNO, A-DIM) falls back to that
    standard's color_index/linetype when the caller doesn't give one, so
    tools/architectural.py (and callers) get a sensible default without
    having to know the convention themselves. An explicit color_index/
    linetype argument always wins over the standard's default."""
    standard = ARCHITECTURAL_LAYERS.get(name)
    if standard is not None:
        if color_index is None:
            color_index = standard["color_index"]
        if linetype is None:
            linetype = standard["linetype"]
    return create_layer(name, color_index=color_index, linetype=linetype)


# ======= blocks.py =======

from tools.common import as_list, deg_to_rad, get_entity, model_space, point, read, verify_count_and_type

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
