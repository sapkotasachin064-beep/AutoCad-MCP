"""Backend-neutral drafting plans.

A generator (floor plans, grids, stairs, sheets) is pure: it returns a Plan
-- the layers it needs and an ordered list of Primitives, each with a stable
`tag` -- without touching any CAD engine. backends/targets.py emits a Plan
into a live AutoCAD document or an ezdxf document and returns tag -> handle.

This gives every generator, on both backends:
  * a dry run (Plan.summary) that shows exactly what would be drawn;
  * one verification rule: model-space entity count must grow by exactly
    the number of primitives;
  * unit tests without AutoCAD (RecordingTarget).
"""

import math
from collections import Counter
from dataclasses import dataclass, field

PRIMITIVE_KINDS = ("line", "polyline", "arc", "circle", "text", "mtext", "dim_aligned", "dim_linear", "hatch")


@dataclass
class Primitive:
    kind: str
    layer: str
    tag: str
    points: tuple = ()  # line: (p1, p2); polyline: vertices; hatch: boundary; dims: (p1, p2)
    closed: bool = False
    polyline_kind: str = "3d"  # "3d" = AcDb3dPolyline / POLYLINE (V0.2.x walls) or "2d" = LWPOLYLINE
    center: tuple | None = None
    radius: float | None = None
    start_angle: float | None = None  # degrees, counterclockwise from +X
    end_angle: float | None = None
    text: str | None = None
    height: float | None = None
    width: float = 0.0
    rotation: float = 0.0  # degrees
    location: tuple | None = None  # text insertion / dimension-line point
    attach: str = "top_left"  # mtext attachment: top_left | middle_center
    pattern: str | None = None
    scale: float = 1.0

    def __post_init__(self):
        if self.kind not in PRIMITIVE_KINDS:
            raise ValueError(f"unknown primitive kind {self.kind!r}")

    def extent_points(self) -> list:
        if self.kind in ("arc", "circle"):
            cx, cy = self.center[0], self.center[1]
            r = self.radius
            return [(cx - r, cy - r), (cx + r, cy + r)]
        if self.kind in ("text", "mtext"):
            return [self.location[:2]]
        pts = [p[:2] for p in self.points]
        if self.location is not None:
            pts.append(self.location[:2])
        return pts

    def describe(self) -> dict:
        out = {"kind": self.kind, "layer": self.layer, "tag": self.tag}
        if self.points:
            out["points"] = [list(map(lambda v: round(v, 6), p)) for p in self.points]
        if self.closed:
            out["closed"] = True
        if self.center is not None:
            out.update(center=list(self.center), radius=self.radius)
        if self.start_angle is not None:
            out.update(start_angle=self.start_angle, end_angle=self.end_angle)
        if self.text is not None:
            out.update(text=self.text, height=self.height)
        if self.location is not None:
            out["location"] = list(self.location)
        if self.pattern:
            out["pattern"] = self.pattern
        return out


@dataclass
class Plan:
    """layers: name -> {"color": ACI or None, "linetype": name or None,
    "force": True to overwrite an existing layer's color (V0.2.3 floor plan
    behaviour), False to leave an existing layer's settings alone}."""

    layers: dict = field(default_factory=dict)
    primitives: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def add(self, primitive: Primitive) -> Primitive:
        self.primitives.append(primitive)
        return primitive

    def layer(self, name: str, color: int | None = None, linetype: str | None = None, force: bool = False):
        self.layers.setdefault(name, {"color": color, "linetype": linetype, "force": force})

    def bbox(self):
        pts = [p for prim in self.primitives for p in prim.extent_points()]
        if not pts:
            return None
        return [[min(p[0] for p in pts), min(p[1] for p in pts)], [max(p[0] for p in pts), max(p[1] for p in pts)]]

    def summary(self, max_primitives: int = 200) -> dict:
        return {
            "primitive_count": len(self.primitives),
            "counts_by_kind": dict(Counter(p.kind for p in self.primitives)),
            "counts_by_layer": dict(Counter(p.layer for p in self.primitives)),
            "layers": self.layers,
            "bbox": self.bbox(),
            "primitives": [p.describe() for p in self.primitives[:max_primitives]],
            "primitives_truncated": len(self.primitives) > max_primitives,
        }


def rect_points(x0, y0, x1, y1, z=0.0):
    return ((x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z))


def polar(origin, angle_deg, distance):
    a = math.radians(angle_deg)
    return (origin[0] + distance * math.cos(a), origin[1] + distance * math.sin(a), origin[2] if len(origin) > 2 else 0.0)
