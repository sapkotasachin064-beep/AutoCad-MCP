"""Emit a domain.plan.Plan into a drawing.

ComTarget draws into a live AutoCAD document (caller is already on the COM
thread with the document open for writing), DxfTarget into an ezdxf
document, RecordingTarget into a list (tests). `emit` returns {tag: handle}
and verifies model-space entity count grew by exactly len(plan.primitives).
"""

import contextlib
import math

from core import session
from core.errors import VerificationError
from domain import units

# Dimension primitives that carry a text `height` get their text, arrows and
# extension lines sized from it (units.dimension_sizes), so a dimension drawn in a
# millimetre drawing is as readable as one in an inch drawing. The primitive's
# dim_scale is the dimension's DIMSCALE (None = 1: `height` is then the size that
# is drawn). Primitives without a height (the older generators) keep the
# drawing's current dimension style.
_COM_DIMENSION_PROPERTIES = (
    ("ScaleFactor", "scale"),  # DIMSCALE
    ("TextHeight", "text_height"),
    ("ArrowheadSize", "arrow"),
    ("ExtensionLineExtend", "extension_beyond"),
    ("ExtensionLineOffset", "extension_offset"),
    ("TextGap", "text_gap"),
    ("PrimaryUnitsPrecision", "decimals"),  # AcDimPrecision: the value is the number of decimal places
)


def dxf_dimension_override(height, insunits=None, scale=None) -> dict:
    """ezdxf dimension style overrides.

    Always dimlfac=1: ezdxf's default dimension style shows every measurement times 100 (it assumes metres
    displayed as centimetres), so a 4000 mm span would read 400000. With a text height the text, arrows and
    extension lines are sized from it and the text shows the decimals that suit the drawing's units; ezdxf
    multiplies those sizes by dimscale (`scale`, default 1) when it draws the dimension."""
    override = {"dimlfac": 1.0}
    if height:
        sizes = units.dimension_sizes(height)
        override.update(dimscale=float(scale or 1.0), dimtxt=sizes["text_height"], dimasz=sizes["arrow"],
                        dimexe=sizes["extension_beyond"], dimexo=sizes["extension_offset"],
                        dimgap=sizes["text_gap"], dimdec=units.dimension_decimals(insunits))
    return override


def read_dimscale(doc):
    """The drawing's DIMSCALE system variable, or None when AutoCAD does not answer."""
    from backends.com_engine import _get_variable

    value = _get_variable(doc, "DIMSCALE")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


@contextlib.contextmanager
def dimension_scale_scope(doc, scale, *, keep=False):
    """AutoCAD gives a new dimension the drawing's DIMSCALE, so make it `scale` while dimensions are created.

    keep=False puts the drawing's own value back afterwards (the plan generators, whose sizes are absolute: a
    DIMSCALE of 50 set earlier must not make their 150 mm text 7500 mm). keep=True leaves `scale` as the
    drawing's DIMSCALE (autocad_add_dimension: the next dimension, drawn by a tool or by hand, then agrees)."""
    import pywintypes

    from backends.com_engine import _get_variable, _retry_com

    before = _get_variable(doc, "DIMSCALE")
    changed = False
    # An unreadable DIMSCALE could not be put back, so only a scale that is kept is set then.
    if (before is None and keep) or (before is not None and float(before) != float(scale)):
        try:
            _retry_com(lambda: doc.SetVariable("DIMSCALE", float(scale)))
            changed = True
        except (pywintypes.com_error, AttributeError) as exc:
            session.add_notice("dimscale_not_set", scale=float(scale), error=str(exc))
    try:
        yield
    finally:
        if changed and not keep and before is not None:
            try:
                _retry_com(lambda: doc.SetVariable("DIMSCALE", float(before)))
            except (pywintypes.com_error, AttributeError) as exc:
                session.add_notice("dimscale_not_restored", scale=float(before), error=str(exc))


def size_com_dimension(entity, insunits, height, scale=None, tag=None):
    """Size one live dimension: `height` is the text height before DIMSCALE (`scale`, default 1), arrows and
    extension lines follow from it (units.dimension_sizes). A property AutoCAD refuses is reported as a
    notice, not hidden: the dimension is still drawn, with the style's size. Returns how many were refused."""
    import pywintypes

    sizes = {**units.dimension_sizes(height), "decimals": units.dimension_decimals(insunits),
             "scale": float(scale or 1.0)}
    refused = 0
    for prop, key in _COM_DIMENSION_PROPERTIES:
        try:
            setattr(entity, prop, sizes[key])
        except (pywintypes.com_error, AttributeError) as exc:
            refused += 1
            session.add_notice("dimension_size_not_applied", property=prop, tag=tag, error=str(exc))
    return refused


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
            override = dxf_dimension_override(p.height, self.insunits, p.dim_scale)
            if p.kind == "dim_aligned":
                dim = msp.add_aligned_dim(p1=p.points[0][:2], p2=p.points[1][:2],
                                          distance=_aligned_distance(p), override=override, dxfattribs=attribs)
            else:
                dim = msp.add_linear_dim(base=p.location[:2], p1=p.points[0][:2], p2=p.points[1][:2],
                                         angle=p.rotation, override=override, dxfattribs=attribs)
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
        from backends import com_engine as cad_engine
        from tools.common import model_space

        self.doc = doc
        self.space = model_space(doc)
        self.insunits = cad_engine.read_insunits(doc)
        self._layer_before = None  # the drawing's current layer before the first entity, put back by finish()
        self._layer_now = None
        self._refused = set()  # layers AutoCAD would not make current

    def count(self) -> int:
        from backends.com_engine import _retry_com

        return _retry_com(lambda: self.space.Count)

    def _draw_on(self, name):
        """Make `name` the current layer, so the entity drawn next is created on it directly instead of on
        whatever layer was current (usually 0) and moved afterwards. If AutoCAD refuses (a frozen layer), the
        entity is still moved onto the layer after it is created, and draw() reads the layer back."""
        import pywintypes

        from backends.com_engine import _get_variable, _retry_com

        if self._layer_now is None:
            self._layer_before = _get_variable(self.doc, "CLAYER")
            self._layer_now = str(self._layer_before or "")
        if self._layer_before is None:  # unreadable, so it could not be put back: leave it alone
            return
        if self._layer_now.lower() == name.lower() or name in self._refused:
            return
        try:
            _retry_com(lambda: self.doc.SetVariable("CLAYER", name))
            self._layer_now = name
        except (pywintypes.com_error, AttributeError) as exc:
            self._refused.add(name)
            session.add_notice("layer_not_made_current", layer=name, error=str(exc))

    def finish(self):
        """Put the drawing's current layer back where it was before emit() started drawing."""
        import pywintypes

        from backends.com_engine import _retry_com

        before, now = self._layer_before, self._layer_now
        self._layer_before = self._layer_now = None
        if before and now and str(before).lower() != now.lower():
            try:
                _retry_com(lambda: self.doc.SetVariable("CLAYER", before))
            except (pywintypes.com_error, AttributeError) as exc:
                session.add_notice("current_layer_not_restored", layer=str(before), error=str(exc))

    def ensure_layer(self, name, color=None, linetype=None, force=False):
        import pywintypes

        from backends.com_engine import _retry_com
        from tools.drawing import ensure_linetype

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

    def _size_dimension(self, entity, p):
        """Scale one dimension's text, arrows and extension lines from p.height
        (see units.dimension_sizes). A property AutoCAD refuses is reported as a
        notice, not hidden: the dimension is still drawn, with the style's size."""
        if p.height:
            size_com_dimension(entity, self.insunits, p.height, p.dim_scale, p.tag)

    def _dimension_scope(self, p):
        """Dimensions with a text height are created with DIMSCALE = p.dim_scale (default 1), whatever DIMSCALE
        the drawing carries; the drawing's own value is put back afterwards."""
        if not p.height:
            return contextlib.nullcontext()
        return dimension_scale_scope(self.doc, p.dim_scale or 1.0)

    def draw(self, p) -> str:
        from backends.com_engine import _retry_com, flat_variant, point_variant
        from tools.annotation import AC_HATCH_PATTERN_PREDEFINED
        from tools.common import dispatch_array, double_array

        space = self.space
        self._draw_on(p.layer)

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
            with self._dimension_scope(p):
                entity = _retry_com(lambda: space.AddDimAligned(pt(p.points[0]), pt(p.points[1]), pt(p.location)))
                self._size_dimension(entity, p)
        elif p.kind == "dim_linear":
            with self._dimension_scope(p):
                entity = _retry_com(lambda: space.AddDimRotated(pt(p.points[0]), pt(p.points[1]), pt(p.location),
                                                                math.radians(p.rotation)))
                self._size_dimension(entity, p)
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
        # The entity was created on p.layer when AutoCAD let that layer be current; setting it again covers the
        # rest. Reading it back means an entity AutoCAD left on another layer (a hatch on 0) is an error, not
        # a drawing that looks fine until someone checks the layers.
        _retry_com(lambda: setattr(entity, "Layer", p.layer))
        placed = _retry_com(lambda: entity.Layer)
        if str(placed).lower() != p.layer.lower():
            raise VerificationError(
                f"{p.kind} {p.tag!r} is on layer {placed!r}, not {p.layer!r}.",
                details={"tag": p.tag, "kind": p.kind, "expected_layer": p.layer, "layer_read_back": str(placed)})
        return _retry_com(lambda: entity.Handle)


def emit(plan, target) -> dict:
    """Draw every primitive of plan into target; return {tag: handle}."""
    for name, spec in plan.layers.items():
        target.ensure_layer(name, spec.get("color"), spec.get("linetype"), spec.get("force", False))
    before = target.count()
    handles = {}
    try:
        for primitive in plan.primitives:
            handles[primitive.tag] = target.draw(primitive)
    finally:
        finish = getattr(target, "finish", None)
        if finish is not None:
            finish()
    after = target.count()
    if after != before + len(plan.primitives):
        raise VerificationError(
            f"Plan emission could not be verified: expected {len(plan.primitives)} new entities, "
            f"model space went {before} -> {after}.",
            details={"expected": len(plan.primitives), "before": before, "after": after},
        )
    return handles
