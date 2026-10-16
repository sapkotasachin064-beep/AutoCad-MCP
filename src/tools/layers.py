"""Layer creation and the shared helper draw tools use to put an entity on a
named layer without touching the document's ActiveLayer (and therefore
without silently changing what every other draw command targets)."""

import pywintypes

from cad_engine import _retry_com, com_initialized, get_active_document, get_connected_app, get_drawing_identity
from core.errors import CadStateError
from utils import geometry
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
