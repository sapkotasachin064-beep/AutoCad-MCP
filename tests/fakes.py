"""A small recorded fake of AutoCAD's ActiveX object model for behaviour
tests of the COM tool modules.

It models only what the tools call, with plausible semantics (handles,
ModelSpace counts, bounding boxes, layers, attributes, save/close state).
Passing tests prove the tools' call sequences and checks, NOT AutoCAD's own
behaviour -- that needs the live tests in test_integration_autocad.py.
"""

import itertools
import math
import os

import pywintypes

_handles = itertools.count(0x100)
KEY_NOT_FOUND = -2145386476


def _v(value):
    """Unwrap a win32com VARIANT (point_variant / flat_variant) to a tuple."""
    return tuple(getattr(value, "value", value))


def com_error(text="Key not found", hresult=-2147352567):
    return pywintypes.com_error(hresult, "Exception occurred.", (0, "AutoCAD", text, None, 0, KEY_NOT_FOUND), None)


class FakeEntity:
    def __init__(self, space, object_name, **geometry):
        self._space = space
        self.ObjectName = object_name
        self.Handle = f"{next(_handles):X}"
        self.Layer = "0"
        self.Color = 256
        self.Linetype = "ByLayer"
        self.Lineweight = -1
        self.Visible = True
        self.erased = False
        self.highlighted = False
        for key, value in geometry.items():
            setattr(self, key, value)

    # --- geometry -------------------------------------------------------
    def _points(self):
        if self.ObjectName == "AcDbLine":
            return [self.StartPoint, self.EndPoint]
        if self.ObjectName in ("AcDb3dPolyline", "AcDbPolyline"):
            step = 3 if self.ObjectName == "AcDb3dPolyline" else 2
            c = list(self.Coordinates)
            return [tuple(c[i:i + step]) + ((0.0,) if step == 2 else ()) for i in range(0, len(c), step)]
        if self.ObjectName in ("AcDbCircle", "AcDbArc"):
            cx, cy, cz = self.Center
            r = self.Radius
            return [(cx - r, cy - r, cz), (cx + r, cy + r, cz)]
        if self.ObjectName in ("AcDbText", "AcDbMText", "AcDbBlockReference"):
            x, y, z = self.InsertionPoint
            h = getattr(self, "Height", 1.0)
            return [(x, y, z), (x + h, y + h, z)]
        return [(0.0, 0.0, 0.0), (1.0, 1.0, 0.0)]

    def _set_points(self, transform):
        if self.ObjectName == "AcDbLine":
            self.StartPoint, self.EndPoint = transform(self.StartPoint), transform(self.EndPoint)
        elif self.ObjectName in ("AcDb3dPolyline", "AcDbPolyline"):
            step = 3 if self.ObjectName == "AcDb3dPolyline" else 2
            c = list(self.Coordinates)
            out = []
            for i in range(0, len(c), step):
                p = transform(tuple(c[i:i + step]) + ((0.0,) if step == 2 else ()))
                out.extend(p[:step])
            self.Coordinates = tuple(out)
        elif self.ObjectName in ("AcDbCircle", "AcDbArc"):
            self.Center = transform(self.Center)
        elif hasattr(self, "InsertionPoint"):
            self.InsertionPoint = transform(self.InsertionPoint)

    def GetBoundingBox(self):
        pts = self._points()
        lo = tuple(min(p[i] for p in pts) for i in range(3))
        hi = tuple(max(p[i] for p in pts) for i in range(3))
        return lo, hi

    @property
    def Length(self):
        pts = self._points()
        if self.ObjectName == "AcDbLine":
            return math.dist(pts[0], pts[1])
        if self.ObjectName in ("AcDb3dPolyline", "AcDbPolyline"):
            seq = pts + ([pts[0]] if getattr(self, "Closed", False) else [])
            return sum(math.dist(a, b) for a, b in zip(seq, seq[1:]))
        raise com_error("no Length")

    @property
    def Area(self):
        if self.ObjectName == "AcDbCircle":
            return math.pi * self.Radius ** 2
        if self.ObjectName == "AcDbPolyline" or self.ObjectName == "AcDbHatch":
            pts = self._points() if self.ObjectName == "AcDbPolyline" else self._hatch_points
            return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2.0
        raise com_error("no Area")

    # --- editing --------------------------------------------------------
    def Move(self, p1, p2):
        a, b = _v(p1), _v(p2)
        d = tuple(b[i] - a[i] for i in range(3))
        self._set_points(lambda p: tuple(p[i] + d[i] for i in range(3)))

    def Rotate(self, base, angle):
        bx, by, bz = _v(base)
        c, s = math.cos(angle), math.sin(angle)
        self._set_points(lambda p: (bx + (p[0] - bx) * c - (p[1] - by) * s,
                                    by + (p[0] - bx) * s + (p[1] - by) * c, p[2]))

    def ScaleEntity(self, base, factor):
        bx, by, bz = _v(base)
        self._set_points(lambda p: (bx + (p[0] - bx) * factor, by + (p[1] - by) * factor, bz + (p[2] - bz) * factor))
        if hasattr(self, "Radius"):
            self.Radius *= factor

    def _clone(self):
        clone = FakeEntity(self._space, self.ObjectName)
        for key, value in vars(self).items():
            if key not in ("Handle", "_space"):
                setattr(clone, key, value)
        clone.erased = False
        self._space._items.append(clone)
        self._space._doc._by_handle[clone.Handle] = clone
        return clone

    def Copy(self):
        return self._clone()

    def Mirror(self, p1, p2):
        a, b = _v(p1), _v(p2)
        clone = self._clone()
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy)
        ux, uy = dx / n, dy / n

        def reflect(p):
            px, py = p[0] - a[0], p[1] - a[1]
            dot = px * ux + py * uy
            return (a[0] + 2 * dot * ux - px, a[1] + 2 * dot * uy - py, p[2])

        clone._set_points(reflect)
        return clone

    def Offset(self, distance):
        if self.ObjectName not in ("AcDbLine", "AcDbCircle", "AcDbArc", "AcDbPolyline"):
            raise com_error("Invalid input")
        clone = self._clone()
        if hasattr(clone, "Radius"):
            clone.Radius += distance
        else:
            clone._set_points(lambda p: (p[0], p[1] + distance, p[2]))
        return (clone,)

    def ArrayRectangular(self, rows, cols, levels, row_dist, col_dist, level_dist):
        out = []
        for r in range(rows):
            for c in range(cols):
                if r == 0 and c == 0:
                    continue
                clone = self._clone()
                clone._set_points(lambda p, r=r, c=c: (p[0] + c * col_dist, p[1] + r * row_dist, p[2]))
                out.append(clone)
        return tuple(out)

    def Delete(self):
        self.erased = True
        self._space._items.remove(self)

    def Highlight(self, on):
        self.highlighted = bool(on)

    # --- hatch / blocks -------------------------------------------------
    def AppendOuterLoop(self, loop):
        objects = list(getattr(loop, "value", loop))
        self._hatch_points = [p[:2] for p in objects[0]._points()]

    def Evaluate(self):
        pass

    def GetAttributes(self):
        return tuple(self._attributes)


class FakeSpace:
    def __init__(self, doc):
        self._doc = doc
        self._items = []
        self.Layout = FakeLayout("Model", model=True)

    @property
    def Count(self):
        return len(self._items)

    def Item(self, index):
        return self._items[index]

    def _add(self, object_name, **geometry):
        entity = FakeEntity(self, object_name, **geometry)
        self._items.append(entity)
        self._doc._by_handle[entity.Handle] = entity
        self._doc.Saved = False
        return entity

    def AddLine(self, p1, p2):
        return self._add("AcDbLine", StartPoint=_v(p1), EndPoint=_v(p2), Angle=0.0)

    def AddCircle(self, c, r):
        return self._add("AcDbCircle", Center=_v(c), Radius=r)

    def AddArc(self, c, r, a0, a1):
        return self._add("AcDbArc", Center=_v(c), Radius=r, StartAngle=a0, EndAngle=a1,
                         ArcLength=r * ((a1 - a0) % (2 * math.pi)))

    def Add3DPoly(self, flat):
        return self._add("AcDb3dPolyline", Coordinates=_v(flat), Closed=False)

    def AddLightWeightPolyline(self, flat):
        return self._add("AcDbPolyline", Coordinates=_v(flat), Closed=False)

    def AddText(self, text, p, h):
        return self._add("AcDbText", TextString=text, InsertionPoint=_v(p), Height=h, Rotation=0.0)

    def AddMText(self, p, width, text):
        return self._add("AcDbMText", TextString=text, InsertionPoint=_v(p), Width=width, Height=2.5, Rotation=0.0)

    def AddDimAligned(self, p1, p2, loc):
        a, b = _v(p1), _v(p2)
        return self._add("AcDbAlignedDimension", Measurement=math.dist(a[:2], b[:2]), TextOverride="",
                         InsertionPoint=_v(loc))

    def AddDimRotated(self, p1, p2, loc, rot):
        a, b = _v(p1), _v(p2)
        m = abs((b[0] - a[0]) * math.cos(rot) + (b[1] - a[1]) * math.sin(rot))
        return self._add("AcDbRotatedDimension", Measurement=m, TextOverride="", InsertionPoint=_v(loc))

    def AddHatch(self, pattern_type, name, associative):
        return self._add("AcDbHatch", PatternName=name.upper() if pattern_type == 1 else "_USER",
                         PatternType=pattern_type, PatternScale=1.0, PatternAngle=0.0, _hatch_points=[])

    def InsertBlock(self, p, name, xs, ys, zs, rot):
        block = self._doc.Blocks.Item(name)
        attrs = [FakeAttribute(tag) for tag in block.attdefs]
        return self._add("AcDbBlockReference", InsertionPoint=_v(p), Name=name, EffectiveName=name,
                         Rotation=rot, XScaleFactor=xs, YScaleFactor=ys, ZScaleFactor=zs,
                         HasAttributes=bool(attrs), _attributes=attrs)


class FakeAttribute:
    def __init__(self, tag):
        self.TagString = tag
        self.TextString = ""
        self.Handle = f"{next(_handles):X}"


class FakeLayer:
    def __init__(self, name):
        self.Name = name
        self.LayerOn, self.Freeze, self.Lock = True, False, False
        self.Color, self.Linetype, self.Lineweight, self.Plottable = 7, "Continuous", -3, True


class FakeCollection:
    def __init__(self, items=None, factory=None):
        self._items = dict(items or {})
        self._factory = factory

    @property
    def Count(self):
        return len(self._items)

    def Item(self, key):
        if isinstance(key, int):
            return list(self._items.values())[key]
        for name, value in self._items.items():
            if name.lower() == str(key).lower():
                return value
        raise com_error()

    def Add(self, name):
        self._items[name] = self._factory(name)
        return self._items[name]


class FakeLinetypes(FakeCollection):
    def __init__(self):
        super().__init__({"ByLayer": None, "ByBlock": None, "Continuous": None})
        for name in list(self._items):
            self._items[name] = type("LT", (), {"Name": name})()
        self.library = {"HIDDEN", "CENTER", "DASHED"}

    def Load(self, name, file):
        if name.upper() not in self.library:
            raise com_error("Linetype not found")
        self._items[name.upper()] = type("LT", (), {"Name": name.upper()})()


class FakeBlock:
    def __init__(self, name, attdefs=(), is_layout=False):
        self.Name = name
        self.IsLayout = is_layout
        self.IsXRef = False
        self.attdefs = list(attdefs)
        self._defs = [type("AD", (), {"ObjectName": "AcDbAttributeDefinition", "TagString": t})() for t in attdefs]

    @property
    def Count(self):
        return len(self._defs)

    def Item(self, i):
        return self._defs[i]


class FakeLayout:
    def __init__(self, name, model=False):
        self.Name = name
        self.ModelType = model
        self.TabOrder = 0 if model else 1
        self.ConfigName = "None"
        self.CanonicalMediaName = "Letter"
        self.StyleSheet = ""
        self.PlotType = 0
        self.UseStandardScale = False
        self.StandardScale = 0
        self.CenterPlot = False

    def RefreshPlotDeviceInfo(self):
        pass

    def GetCanonicalMediaNames(self):
        return ("ISO_full_bleed_A3_(420.00_x_297.00_MM)", "ISO_full_bleed_A4_(297.00_x_210.00_MM)", "ANSI_B_(11.00_x_17.00_Inches)")


class FakeSelectionSet:
    def __init__(self, sets, name):
        self._sets, self.Name = sets, name

    def Select(self, mode, *args):
        self.mode = mode

    def Delete(self):
        self._sets.pop(self.Name, None)


class FakePlot:
    def __init__(self, doc):
        self._doc = doc
        self.QuietErrorMode = False
        self.calls = []

    def PlotToFile(self, path, device):
        self.calls.append((path, device, self._doc.vars.get("BACKGROUNDPLOT")))
        with open(path, "wb") as fh:
            fh.write(b"%PDF-1.7\n1 0 obj << /Type /Page /MediaBox [0 0 1190.55 841.89] >>\n%%EOF\n")
        return True


class FakeDocument:
    def __init__(self, app, name="Drawing1.dwg", full_name="", variables=None):
        self._app = app
        self.Name = name
        self.FullName = full_name
        self.Saved = True
        self.ReadOnly = False
        self.vars = {"CMDACTIVE": 0, "LUNITS": 3, "LUPREC": 4, "INSUNITS": 1, "MEASUREMENT": 0,
                     "BACKGROUNDPLOT": 2, "EXTMIN": (0.0, 0.0, 0.0), "EXTMAX": (100.0, 100.0, 0.0),
                     **(variables or {})}
        self._by_handle = {}
        self.ModelSpace = FakeSpace(self)
        self.PaperSpace = FakeSpace(self)
        self.Layers = FakeCollection({"0": FakeLayer("0")}, FakeLayer)
        self.Linetypes = FakeLinetypes()
        self.Blocks = FakeCollection({"*Model_Space": FakeBlock("*Model_Space", is_layout=True)})
        self.Layouts = FakeCollection({"Model": self.ModelSpace.Layout, "Layout1": FakeLayout("Layout1")})
        self.ActiveLayout = self.ModelSpace.Layout
        self.ActiveLayer = self.Layers.Item("0")
        self._sets = {}
        self.Plot = FakePlot(self)
        self.sent = []
        self.saves = []

    @property
    def SelectionSets(self):
        doc = self

        class _Sets:
            def Add(self_inner, name):
                doc._sets[name] = FakeSelectionSet(doc._sets, name)
                return doc._sets[name]

        return _Sets()

    def GetVariable(self, name):
        return self.vars.get(name, 0)

    def SetVariable(self, name, value):
        self.vars[name] = value

    def SendCommand(self, text):
        self.sent.append(text)

    def Regen(self, which):
        self.regens = getattr(self, "regens", 0) + 1

    def HandleToObject(self, handle):
        entity = self._by_handle.get(handle.upper())
        if entity is None or entity.erased:
            raise com_error("Invalid handle")
        return entity

    def Save(self):
        with open(self.FullName, "wb") as fh:
            fh.write(b"AC1032 fake dwg")
        self.Saved = True
        self.saves.append(("Save", self.FullName))

    def SaveAs(self, path, save_type):
        with open(path, "wb") as fh:
            fh.write(b"AC1032 fake" if save_type < 13 or save_type % 2 == 0 else b"  0\nSECTION\nfake dxf")
        self.FullName = path
        self.Name = os.path.basename(path)
        self.Saved = True
        self.saves.append(("SaveAs", path, save_type))

    def Export(self, base, extension, selection):
        assert extension == "DXF", "the extension argument must be 'DXF'"
        with open(f"{base}.DXF", "wb") as fh:
            fh.write(b"  0\nSECTION\n  2\nHEADER\n  0\nENDSEC\n  0\nEOF\n")

    def Activate(self):
        self._app._active = self

    def Close(self, save_changes=False):
        self._app._docs.remove(self)
        if self._app._active is self:
            self._app._active = self._app._docs[-1] if self._app._docs else None


class FakeApp:
    def __init__(self):
        self.Version = "24.3s (LMS Tech)"
        self._docs = []
        self._active = None
        doc = FakeDocument(self)
        self._docs.append(doc)
        self._active = doc

    @property
    def ActiveDocument(self):
        return self._active

    @ActiveDocument.setter
    def ActiveDocument(self, doc):
        self._active = doc

    @property
    def Documents(self):
        app = self

        class _Docs:
            @property
            def Count(self_inner):
                return len(app._docs)

            def Item(self_inner, index):
                return app._docs[index]

            def Add(self_inner, template=None):
                doc = FakeDocument(app, name=f"Drawing{len(app._docs) + 1}.dwg")
                app._docs.append(doc)
                app._active = doc
                return doc

            def Open(self_inner, path, read_only=False):
                doc = FakeDocument(app, name=os.path.basename(path), full_name=path)
                doc.ReadOnly = bool(read_only)
                app._docs.append(doc)
                app._active = doc
                return doc

        return _Docs()
