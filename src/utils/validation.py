"""Pure validators and vocabularies shared by both backends (no COM, no
ezdxf), so the headless backend never imports pywin32-backed modules."""

from utils import geometry

# AutoCAD ObjectName -> DXF entity type, so both backends speak one vocabulary.
OBJECT_TO_DXF = {
    "AcDbLine": "LINE",
    "AcDbPolyline": "LWPOLYLINE",
    "AcDb2dPolyline": "POLYLINE",
    "AcDb3dPolyline": "POLYLINE3D",
    "AcDbCircle": "CIRCLE",
    "AcDbArc": "ARC",
    "AcDbEllipse": "ELLIPSE",
    "AcDbSpline": "SPLINE",
    "AcDbPoint": "POINT",
    "AcDbText": "TEXT",
    "AcDbMText": "MTEXT",
    "AcDbBlockReference": "INSERT",
    "AcDbHatch": "HATCH",
    "AcDbRotatedDimension": "DIMENSION",
    "AcDbAlignedDimension": "DIMENSION",
    "AcDbRadialDimension": "DIMENSION",
    "AcDbDiametricDimension": "DIMENSION",
    "AcDb2LineAngularDimension": "DIMENSION",
    "AcDb3PointAngularDimension": "DIMENSION",
    "AcDbOrdinateDimension": "DIMENSION",
    "AcDbArcDimension": "DIMENSION",
    "AcDbLeader": "LEADER",
    "AcDbMLeader": "MULTILEADER",
    "AcDbTable": "ACAD_TABLE",
    "AcDbRegion": "REGION",
    "AcDb3dSolid": "3DSOLID",
    "AcDbXline": "XLINE",
    "AcDbRay": "RAY",
    "AcDbTrace": "TRACE",
    "AcDbSolid": "SOLID",
    "AcDbViewport": "VIEWPORT",
    "AcDbRasterImage": "IMAGE",
    "AcDbWipeout": "WIPEOUT",
    "AcDbAttributeDefinition": "ATTDEF",
}
DXF_TYPES = frozenset(OBJECT_TO_DXF.values())

# Entity lineweights (hundredths of mm; -1 ByLayer, -2 ByBlock, -3 Default)
VALID_LINEWEIGHTS = frozenset(
    {-3, -2, -1, 0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211}
)
# Layers cannot be ByLayer/ByBlock.
LAYER_LINEWEIGHTS = VALID_LINEWEIGHTS - {-1, -2}

DIMENSION_KINDS = ("aligned", "linear")


def validate_handles(handles, label: str = "handles", maximum: int = 5000) -> list[str]:
    if not isinstance(handles, list) or not handles:
        raise geometry.ValidationError(f"{label} must be a non-empty list of entity handles")
    if len(handles) > maximum:
        raise geometry.ValidationError(f"{label} has {len(handles)} entries; the maximum per call is {maximum}")
    seen, ordered = set(), []
    for h in handles:
        h = geometry.validate_handle(h)
        if h.upper() not in seen:
            seen.add(h.upper())
            ordered.append(h)
    return ordered


def validate_entity_types(entity_types):
    if entity_types is None:
        return None
    if not isinstance(entity_types, list) or not entity_types:
        raise geometry.ValidationError("entity_types must be a non-empty list of DXF type names, e.g. ['LINE']")
    wanted = {str(t).strip().upper() for t in entity_types}
    unknown = wanted - DXF_TYPES
    if unknown:
        raise geometry.ValidationError(f"unknown entity_types {sorted(unknown)}; known: {sorted(DXF_TYPES)}")
    return wanted


def validate_layer_filter(layers):
    if layers is None:
        return None
    if not isinstance(layers, list) or not layers or not all(isinstance(n, str) and n for n in layers):
        raise geometry.ValidationError("layers must be a non-empty list of layer names")
    return {n.lower() for n in layers}


def validate_bbox(bbox):
    if bbox is None:
        return None
    if not isinstance(bbox, list) or len(bbox) != 2:
        raise geometry.ValidationError("bbox must be [[xmin, ymin], [xmax, ymax]]")
    lo = geometry.validate_point_2d_or_3d(bbox[0], "bbox[0]")
    hi = geometry.validate_point_2d_or_3d(bbox[1], "bbox[1]")
    if lo[0] > hi[0] or lo[1] > hi[1]:
        raise geometry.ValidationError("bbox[0] must be the lower-left corner and bbox[1] the upper-right")
    return lo, hi


def box_inside(box, window) -> bool:
    lo, hi = window
    bmin, bmax = box
    return bmin[0] >= lo[0] and bmin[1] >= lo[1] and bmax[0] <= hi[0] and bmax[1] <= hi[1]


def validate_color_for_entity(color_index):
    """ACI 0-255, or 256 (ByLayer), which entities accept and layers don't."""
    if color_index == 256 and not isinstance(color_index, bool):
        return 256
    return geometry.validate_color_index(color_index, "color_index")
