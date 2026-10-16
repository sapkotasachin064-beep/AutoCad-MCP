"""Emit a domain.plan.Plan into a drawing.

ComTarget draws into a live AutoCAD document (caller is already on the COM
thread with the document open for writing), DxfTarget into an ezdxf
document, RecordingTarget into a list (tests). `emit` returns {tag: handle}
and verifies model-space entity count grew by exactly len(plan.primitives).
"""

import math

from core.errors import VerificationError


class RecordingTarget:
    """Records primitives instead of drawing them. Handles are sequential."""

    def __init__(self, insunits: int = 1):
        self.insunits = insunits
        self.drawn = []
        self.layers = {}

    def count(self) -> int:
        return len(self.drawn)

    def ensure_layer(self, name, color=None, linetype=None, force=False):
        self.layers.setdefault(name, {"color": color, "linetype": linetype})
        if force and color is not None:
            self.layers[name]["color"] = color

    def draw(self, primitive) -> str:
        self.drawn.append(primitive)
        return f"R{len(self.drawn):X}"


class DxfTarget:
    def __init__(self, doc):
        self.doc = doc
        self.msp = doc.modelspace()
        self.insunits = doc.header.get("$INSUNITS", 0)

    def count(self) -> int:
        return len(self.msp)

    def ensure_layer(self, name, color=None, linetype=None, force=False):
        layers = self.doc.layers
        if name in layers:
            layer = layers.get(name)
            if force and color is not None:
                layer.color = color
            return
        attribs = {}
        if color is not None:
            attribs["color"] = color
        if linetype and linetype in self.doc.linetypes:
            attribs["linetype"] = linetype
        layers.add(name, **attribs)

    def draw(self, p) -> str:
        msp, attribs = self.msp, {"layer": p.layer}
        if p.kind == "line":
            entity = msp.add_line(p.points[0], p.points[1], dxfattribs=attribs)
        elif p.kind == "polyline":
            if p.polyline_kind == "2d":
                entity = msp.add_lwpolyline([q[:2] for q in p.points], close=p.closed, dxfattribs=attribs)
            else:
                entity = msp.add_polyline3d([tuple(q) + (0.0,) * (3 - len(q)) for q in p.points],
                                            close=p.closed, dxfattribs=attribs)
        elif p.kind == "arc":
            entity = msp.add_arc(p.center, p.radius, p.start_angle, p.end_angle, dxfattribs=attribs)
        elif p.kind == "circle":
            entity = msp.add_circle(p.center, p.radius, dxfattribs=attribs)
        elif p.kind == "text":
            entity = msp.add_text(p.text, height=p.height, rotation=p.rotation, dxfattribs=attribs)
            entity.set_placement(p.location)
        elif p.kind == "mtext":
            entity = msp.add_mtext(p.text, dxfattribs={**attribs, "char_height": p.height, "width": p.width,
                                                        "rotation": p.rotation})
            entity.set_location(p.location, attachment_point=5 if p.attach == "middle_center" else 1)
        elif p.kind in ("dim_aligned", "dim_linear"):
            if p.kind == "dim_aligned":
                dim = msp.add_aligned_dim(p1=p.points[0][:2], p2=p.points[1][:2],
                                          distance=_aligned_distance(p), dxfattribs=attribs)
            else:
                dim = msp.add_linear_dim(base=p.location[:2], p1=p.points[0][:2], p2=p.points[1][:2],
                                         angle=p.rotation, dxfattribs=attribs)
            dim.render()
            entity = dim.dimension
        elif p.kind == "hatch":
            entity = msp.add_hatch(color=256, dxfattribs=attribs)
            if (p.pattern or "SOLID").upper() == "SOLID":
                entity.set_solid_fill(color=256)
            else:
                entity.set_pattern_fill(p.pattern.upper(), scale=p.scale)
            entity.paths.add_polyline_path([q[:2] for q in p.points], is_closed=True)
        else:  # pragma: no cover - Primitive validates kind
            raise ValueError(p.kind)
        return entity.dxf.handle


def _aligned_distance(p) -> float:
    """Signed offset of the dimension line from p1-p2, through p.location."""
    (x1, y1), (x2, y2) = p.points[0][:2], p.points[1][:2]
    lx, ly = p.location[:2]
    length = math.hypot(x2 - x1, y2 - y1)
    return ((x2 - x1) * (ly - y1) - (y2 - y1) * (lx - x1)) / length


class ComTarget:
    """Live AutoCAD document. Must be used on the COM thread inside
    com_initialized(), with doc opened through get_active_document."""

    def __init__(self, doc):
        import cad_engine
        from tools._common import model_space

        self.doc = doc
        self.space = model_space(doc)
        self.insunits = cad_engine.read_insunits(doc)

    def count(self) -> int:
        from cad_engine import _retry_com

        return _retry_com(lambda: self.space.Count)

    def ensure_layer(self, name, color=None, linetype=None, force=False):
        import pywintypes

        from cad_engine import _retry_com
        from tools.layers import ensure_linetype

        layers = self.doc.Layers
        try:
            layer = _retry_com(lambda: layers.Item(name))
            created = False
        except pywintypes.com_error:
            layer = _retry_com(lambda: layers.Add(name))
            created = True
        if color is not None and (created or force):
            _retry_com(lambda: setattr(layer, "Color", color))
        if linetype and created:
            loaded = ensure_linetype(self.doc, linetype)
            _retry_com(lambda: setattr(layer, "Linetype", loaded))

    def draw(self, p) -> str:
        from cad_engine import _retry_com, flat_variant, point_variant
        from tools.annotation import AC_HATCH_PATTERN_PREDEFINED
        from tools._common import dispatch_array, double_array

        space = self.space

        def pt(q):
            return point_variant(tuple(q) + (0.0,) * (3 - len(q)))

        if p.kind == "line":
            entity = _retry_com(lambda: space.AddLine(pt(p.points[0]), pt(p.points[1])))
        elif p.kind == "polyline":
            if p.polyline_kind == "2d":
                flat = [c for q in p.points for c in q[:2]]
                entity = _retry_com(lambda: space.AddLightWeightPolyline(double_array(flat)))
            else:
                flat = [c for q in p.points for c in (tuple(q) + (0.0,) * (3 - len(q)))]
                entity = _retry_com(lambda: space.Add3DPoly(flat_variant(flat)))
            if p.closed:
                _retry_com(lambda: setattr(entity, "Closed", True))
        elif p.kind == "arc":
            entity = _retry_com(lambda: space.AddArc(pt(p.center), p.radius, math.radians(p.start_angle),
                                                     math.radians(p.end_angle)))
        elif p.kind == "circle":
            entity = _retry_com(lambda: space.AddCircle(pt(p.center), p.radius))
        elif p.kind == "text":
            entity = _retry_com(lambda: space.AddText(p.text, pt(p.location), p.height))
            if p.rotation:
                _retry_com(lambda: setattr(entity, "Rotation", math.radians(p.rotation)))
        elif p.kind == "mtext":
            entity = _retry_com(lambda: space.AddMText(pt(p.location), p.width, p.text))
            _retry_com(lambda: setattr(entity, "Height", p.height))
            if p.attach == "middle_center":
                _retry_com(lambda: setattr(entity, "AttachmentPoint", 5))  # acAttachmentPointMiddleCenter
                _retry_com(lambda: setattr(entity, "InsertionPoint", pt(p.location)))
        elif p.kind == "dim_aligned":
            entity = _retry_com(lambda: space.AddDimAligned(pt(p.points[0]), pt(p.points[1]), pt(p.location)))
        elif p.kind == "dim_linear":
            entity = _retry_com(lambda: space.AddDimRotated(pt(p.points[0]), pt(p.points[1]), pt(p.location),
                                                            math.radians(p.rotation)))
        elif p.kind == "hatch":
            flat = [c for q in p.points for c in q[:2]]
            boundary = _retry_com(lambda: space.AddLightWeightPolyline(double_array(flat)))
            _retry_com(lambda: setattr(boundary, "Closed", True))
            entity = _retry_com(lambda: space.AddHatch(AC_HATCH_PATTERN_PREDEFINED, (p.pattern or "SOLID").upper(),
                                                       False))
            _retry_com(lambda: setattr(entity, "PatternScale", p.scale))
            _retry_com(lambda: entity.AppendOuterLoop(dispatch_array([boundary])))
            _retry_com(lambda: entity.Evaluate())
            _retry_com(lambda: boundary.Delete())
        else:  # pragma: no cover
            raise ValueError(p.kind)
        _retry_com(lambda: setattr(entity, "Layer", p.layer))
        return _retry_com(lambda: entity.Handle)


def emit(plan, target) -> dict:
    """Draw every primitive of plan into target; return {tag: handle}."""
    for name, spec in plan.layers.items():
        target.ensure_layer(name, spec.get("color"), spec.get("linetype"), spec.get("force", False))
    before = target.count()
    handles = {}
    for primitive in plan.primitives:
        handles[primitive.tag] = target.draw(primitive)
    after = target.count()
    if after != before + len(plan.primitives):
        raise VerificationError(
            f"Plan emission could not be verified: expected {len(plan.primitives)} new entities, "
            f"model space went {before} -> {after}.",
            details={"expected": len(plan.primitives), "before": before, "after": after},
        )
    return handles
