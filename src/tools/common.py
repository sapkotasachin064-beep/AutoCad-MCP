"""Helpers shared by the V0.3.0 COM tool modules (documents, query,
annotation, blocks, output, editing2). The V0.2.x modules keep their own
private helpers unchanged.

ActiveX angles are radians and every tool boundary is degrees, so the
conversion happens here and nowhere else.
"""

import math

import pywintypes
import pythoncom
import win32com.client

from backends.com_engine import _retry_com, point_variant
from core.errors import CadStateError, VerificationError

from utils.validation import DXF_TYPES, OBJECT_TO_DXF  # noqa: F401  (re-exported)


def dxf_type(object_name: str) -> str:
    return OBJECT_TO_DXF.get(object_name, object_name)


def deg_to_rad(value: float) -> float:
    return math.radians(value)


def rad_to_deg(value: float) -> float:
    return math.degrees(value)


def model_space(doc):
    return _retry_com(lambda: doc.ModelSpace)


def get_entity(doc, handle: str):
    try:
        return _retry_com(lambda: doc.HandleToObject(handle))
    except pywintypes.com_error as exc:
        raise CadStateError(
            f"No entity found with handle {handle!r}: {exc}",
            code="E_ENTITY_NOT_FOUND",
            details={"handle": handle},
        ) from exc


def read(entity, prop: str, default=None):
    """Best-effort property read: a property this entity type does not have
    raises com_error over dynamic dispatch, which is not an error here."""
    try:
        return _retry_com(lambda: getattr(entity, prop))
    except (pywintypes.com_error, AttributeError):
        return default


def as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def point3(value) -> list[float] | None:
    if value is None:
        return None
    coords = [float(c) for c in value]
    while len(coords) < 3:
        coords.append(0.0)
    return coords[:3]


def bounding_box(entity):
    try:
        min_point, max_point = _retry_com(lambda: entity.GetBoundingBox())
        return [list(min_point), list(max_point)]
    except (pywintypes.com_error, TypeError, ValueError):
        return None


def dispatch_array(objects):
    """VARIANT array of IDispatch, which AppendOuterLoop / AddRegion expect."""
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, list(objects))


def double_array(values):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [float(v) for v in values])


def verify_count_and_type(space, count_before: int, entity, expected_names, *, added: int = 1) -> None:
    count_after = _retry_com(lambda: space.Count)
    object_name = _retry_com(lambda: entity.ObjectName)
    if isinstance(expected_names, str):
        expected_names = {expected_names}
    if count_after != count_before + added or object_name not in expected_names:
        raise VerificationError(
            f"Entity creation could not be verified: expected ModelSpace count {count_before + added} and "
            f"ObjectName in {sorted(expected_names)}, got count {count_after} and ObjectName {object_name!r}.",
            details={"count_before": count_before, "count_after": count_after, "object_name": object_name},
        )


def point(value):
    return point_variant(tuple(value))
