"""Drawing units: presets, AutoCAD's INSUNITS codes, length conversion, and
per-unit-system drafting defaults. Pure Python -- no COM, no ezdxf.

AUTOCAD_MCP_UNITS selects the preset mutating tools apply to the active
drawing (V0.2.3 always forced `engineering`; that stays the default):

  engineering    LUNITS=3 (feet and decimal inches), LUPREC=4, INSUNITS=1 (in), MEASUREMENT=0
  architectural  LUNITS=4 (feet and fractional inches), LUPREC=4, INSUNITS=1 (in), MEASUREMENT=0
  metric_mm      LUNITS=2 (decimal), LUPREC=0, INSUNITS=4 (mm), MEASUREMENT=1
  metric_m       LUNITS=2 (decimal), LUPREC=3, INSUNITS=6 (m), MEASUREMENT=1
  preserve       never change the drawing's unit variables

Tools that size things in real-world units (walls, floor plans, grids) read
the drawing's actual INSUNITS and convert; they never assume inches.
"""

import os
from dataclasses import dataclass

from core.errors import CadError, ConfigError

UNIT_PRESETS = {
    "engineering": (("LUNITS", 3), ("LUPREC", 4), ("INSUNITS", 1), ("MEASUREMENT", 0)),
    "architectural": (("LUNITS", 4), ("LUPREC", 4), ("INSUNITS", 1), ("MEASUREMENT", 0)),
    "metric_mm": (("LUNITS", 2), ("LUPREC", 0), ("INSUNITS", 4), ("MEASUREMENT", 1)),
    "metric_m": (("LUNITS", 2), ("LUPREC", 3), ("INSUNITS", 6), ("MEASUREMENT", 1)),
    "preserve": (),
}
DEFAULT_PRESET = "engineering"

# AutoCAD INSUNITS code -> (name, millimetres per unit). Codes without a fixed
# length (0 unitless, 8 microinches .. only common ones listed) map to None.
INSUNITS = {
    0: ("unitless", None),
    1: ("in", 25.4),
    2: ("ft", 304.8),
    3: ("mi", 1609344.0),
    4: ("mm", 1.0),
    5: ("cm", 10.0),
    6: ("m", 1000.0),
    7: ("km", 1_000_000.0),
    10: ("yd", 914.4),
    14: ("dm", 100.0),
}
UNIT_NAMES = {name: code for code, (name, mm) in INSUNITS.items() if mm is not None}
METRIC_CODES = {4, 5, 6, 7, 14}
IMPERIAL_CODES = {1, 2, 3, 10}


def preset_name() -> str:
    """The preset in force: one chosen at run time with
    autocad_set_drawing_units (core.session), else AUTOCAD_MCP_UNITS."""
    from core import session

    override = session.units_override()
    if override is not None:
        return override
    raw = os.environ.get("AUTOCAD_MCP_UNITS", DEFAULT_PRESET).strip().lower() or DEFAULT_PRESET
    if raw not in UNIT_PRESETS:
        raise ConfigError(f"AUTOCAD_MCP_UNITS={raw!r} is not a preset; use one of {sorted(UNIT_PRESETS)}")
    return raw


def preset_variables(name: str | None = None) -> tuple:
    return UNIT_PRESETS[name or preset_name()]


def unit_code(unit: str) -> int:
    """'in' | 'ft' | 'mm' | 'cm' | 'm' | ... -> INSUNITS code."""
    key = (unit or "").strip().lower()
    aliases = {"inch": "in", "inches": "in", "feet": "ft", "foot": "ft", "millimeter": "mm",
               "millimeters": "mm", "millimetre": "mm", "millimetres": "mm", "meter": "m",
               "meters": "m", "metre": "m", "metres": "m", "centimeter": "cm", "centimeters": "cm"}
    key = aliases.get(key, key)
    if key not in UNIT_NAMES:
        raise CadError(f"unknown unit {unit!r}; use one of {sorted(UNIT_NAMES)}", code="E_INVALID_INPUT")
    return UNIT_NAMES[key]


def mm_per_unit(code: int) -> float:
    entry = INSUNITS.get(code)
    if entry is None or entry[1] is None:
        raise CadError(
            f"drawing units are {describe(code)}, which has no fixed length; set them with "
            "autocad_set_drawing_units or pass the unit explicitly",
            code="E_UNITS_MISMATCH",
            details={"insunits": code},
        )
    return entry[1]


def convert(value: float, from_code: int, to_code: int) -> float:
    return value * mm_per_unit(from_code) / mm_per_unit(to_code)


def describe(code) -> str:
    entry = INSUNITS.get(code)
    return entry[0] if entry else f"INSUNITS={code}"


def is_metric(code: int) -> bool:
    return code in METRIC_CODES


@dataclass(frozen=True)
class DraftingDefaults:
    """Typical residential drafting sizes, in the stated unit. These are
    drafting conventions (brick 9"/4.5" = 230/115 mm walls, common door and
    window sizes), not building-code requirements -- every generator lets the
    caller override them."""

    unit_code: int
    exterior_wall: float
    interior_wall: float
    main_door: float
    interior_door: float
    window: float
    text_height: float


IMPERIAL_DEFAULTS = DraftingDefaults(1, 9.0, 4.5, 36.0, 30.0, 48.0, 6.0)  # inches (V0.2.3 values)
METRIC_DEFAULTS = DraftingDefaults(4, 230.0, 115.0, 900.0, 750.0, 1200.0, 150.0)  # millimetres


def defaults_for(drawing_code: int) -> dict:
    """Drafting defaults converted into the drawing's own units."""
    base = METRIC_DEFAULTS if is_metric(drawing_code) else IMPERIAL_DEFAULTS
    factor = mm_per_unit(base.unit_code) / mm_per_unit(drawing_code)
    return {
        "exterior_wall": base.exterior_wall * factor,
        "interior_wall": base.interior_wall * factor,
        "main_door": base.main_door * factor,
        "interior_door": base.interior_door * factor,
        "window": base.window * factor,
        "text_height": base.text_height * factor,
    }
