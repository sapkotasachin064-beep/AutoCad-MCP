"""Static configuration and naming constants shared across cad_engine and tools.

Covers AutoCAD release support, environment-configurable output/db paths,
AutoCAD ObjectName groupings, and the architectural layer standard used by
tools/architectural.py.
"""

import os

MIN_SUPPORTED_RELEASE = 24.0  # AutoCAD 2021 == internal release 24.0

# Known internal release -> marketing year. AutoCAD exposes no official
# "year" property, only ACADVER release numbers, so this map is best effort
# and extended as new releases ship.
RELEASE_TO_YEAR = {
    24.0: 2021,
    24.1: 2022,
    24.2: 2023,
    24.3: 2024,
    24.4: 2025,
}


def get_output_dir() -> str:
    configured = os.environ.get("AUTOCAD_MCP_OUTPUT_DIR")
    if configured:
        return configured
    return os.path.join(os.path.expanduser("~"), "Documents", "AutoCAD MCP Output")


def get_db_path() -> str:
    configured = os.environ.get("AUTOCAD_MCP_DB_PATH")
    if configured:
        return configured
    return os.path.join(get_output_dir(), "autocad_mcp.db")


# AutoCAD ObjectName constants for entity kinds this server understands.
#
# Detecting "is this a text entity" by ObjectName membership, instead of
# probing with hasattr(entity, "TextString"), matters: a win32com dynamic COM
# object raises pywintypes.com_error (not AttributeError) for a property that
# doesn't exist on that entity's vtable, so hasattr() does not reliably catch
# it and can crash a scan loop on the first non-text entity.
TEXT_OBJECT_NAMES = frozenset({"AcDbText", "AcDbMText"})

SUPPORTED_OBJECT_NAMES = frozenset(
    {"AcDbLine", "AcDbCircle", "AcDb3dPolyline", "AcDbPolyline", "AcDbText", "AcDbMText"}
)

# Architectural layer standard used by tools/architectural.py and
# tools/layers.ensure_layer. color_index is an AutoCAD ACI color (0-255);
# linetype is left None (Continuous) unless noted -- callers passing their
# own color_index/linetype to ensure_layer still override these.
#
# A-WALL-EXT/A-WALL-INT/A-TEXT and A-DIM's color were added/changed for the
# generate_2d_floor_plan macro tool; A-WALL/A-ANNO predate it and are kept for
# autocad_draw_wall and backward compatibility.
ARCHITECTURAL_LAYERS = {
    "A-WALL": {"color_index": 7, "linetype": None},  # white/black, continuous
    "A-WALL-EXT": {"color_index": 3, "linetype": None},  # green
    "A-WALL-INT": {"color_index": 2, "linetype": None},  # yellow
    "A-DOOR": {"color_index": 1, "linetype": None},  # red
    "A-GLAZ": {"color_index": 4, "linetype": None},  # cyan
    "A-ANNO": {"color_index": 2, "linetype": None},  # yellow
    "A-TEXT": {"color_index": 7, "linetype": None},  # white
    "A-DIM": {"color_index": 6, "linetype": None},  # magenta
}
