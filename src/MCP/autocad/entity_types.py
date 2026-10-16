"""AutoCAD ObjectName constants for entity kinds this server understands.

Detecting "is this a text entity" by ObjectName membership, instead of
probing with hasattr(entity, "TextString"), matters: a win32com dynamic COM
object raises pywintypes.com_error (not AttributeError) for a property that
doesn't exist on that entity's vtable, so hasattr() does not reliably catch
it and can crash a scan loop on the first non-text entity.
"""

TEXT_OBJECT_NAMES = frozenset({"AcDbText", "AcDbMText"})

SUPPORTED_OBJECT_NAMES = frozenset(
    {"AcDbLine", "AcDbCircle", "AcDb3dPolyline", "AcDbPolyline", "AcDbText", "AcDbMText"}
)
