"""Layer creation and the shared helper draw tools use to put an entity on a
named layer without touching the document's ActiveLayer (and therefore
without silently changing what every other draw command targets)."""

import pywintypes

from . import geometry
from .connection import _retry_com, com_initialized, get_active_document, get_connected_app
from .identity import get_drawing_identity


def get_or_create_layer(doc, name: str):
    try:
        return _retry_com(lambda: doc.Layers.Item(name))
    except pywintypes.com_error:
        try:
            return _retry_com(lambda: doc.Layers.Add(name))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create layer {name!r}: {exc}") from exc


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
            "drawing_identity": identity.identity,
            "message": f"Layer {name!r} {'created' if not existed else 'updated'}.",
        }
