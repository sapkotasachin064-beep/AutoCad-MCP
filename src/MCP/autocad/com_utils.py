"""VARIANT conversion helpers shared by entity creation and editing."""

import pythoncom
import win32com.client


def point_variant(point: tuple[float, float, float]):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(point))


def flat_variant(values: list[float]):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(values))
