"""Headless DXF backend (AUTOCAD_MCP_BACKEND=dxf).

One ezdxf document is held by the server process: created with
autocad_create_new_drawing or loaded with autocad_open_drawing (DXF only --
ezdxf cannot read or write DWG), edited by the same tools as the live
backend, written with autocad_save_drawing / autocad_export_dxf. Nothing here
starts or talks to AutoCAD. Every result carries backend="dxf".

Contract parity with the live backend: same arguments, same validation
(utils/geometry.py), same result keys, same document pin and units policy
(applied to the DXF header). Differences are explicit refusals
(E_UNSUPPORTED_BACKEND with a reason): no highlighting (no display), no
AutoCAD plotting (use autocad_render_preview), no DWG. All operations are
serialised by one lock -- ezdxf documents are not thread-safe.
"""

import importlib.util
import math
import os
import re
import threading
import uuid
from collections import Counter
from pathlib import Path

from backends.base import Backend
from core import session
from core.errors import CadError, CadStateError, DependencyMissingError, VerificationError
from core.evidence import file_evidence, page, validate_limit, validate_offset
from core.paths import input_path, output_path
from domain import civil, units
from utils import geometry
from utils.constants import ARCHITECTURAL_LAYERS, get_db_path
from utils.validation import MAX_CIVIL_PLACE_POINTS, MAX_CIVIL_PROFILE_SAMPLES, MAX_CIVIL_QUERY_POINTS

DXF_VERSIONS = {"R2000": "AC1015", "R2004": "AC1018", "R2007": "AC1021", "R2010": "AC1024",
                "R2013": "AC1027", "R2018": "AC1032"}
DXF_TO_OBJECT = {"LINE": "AcDbLine", "LWPOLYLINE": "AcDbPolyline", "POLYLINE3D": "AcDb3dPolyline",
                 "POLYLINE": "AcDb2dPolyline", "CIRCLE": "AcDbCircle", "ARC": "AcDbArc", "TEXT": "AcDbText",
                 "MTEXT": "AcDbMText", "INSERT": "AcDbBlockReference", "HATCH": "AcDbHatch",
                 "ELLIPSE": "AcDbEllipse", "SPLINE": "AcDbSpline", "POINT": "AcDbPoint", "DIMENSION": "AcDbDimension"}
TEXT_TYPES = ("TEXT", "MTEXT")
MAX_VERTICES = 2000


def ezdxf_version() -> str | None:
    if importlib.util.find_spec("ezdxf") is None:
        return None
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("ezdxf")
    except PackageNotFoundError:
        return "unknown"


def _require_ezdxf():
    if ezdxf_version() is None:
        raise DependencyMissingError('ezdxf is not installed; install the headless extra: pip install -e ".[dxf]"')
    import ezdxf

    return ezdxf


def _p3(v):
    return [float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0]


def _bulge_arc(p1, p2, bulge):
    """(arc length, signed segment area) of a bulged polyline segment."""
    chord = math.dist(p1, p2)
    if not bulge or chord == 0:
        return chord, 0.0
    theta = 4.0 * math.atan(bulge)
    radius = chord / (2.0 * math.sin(abs(theta) / 2.0))
    sector = 0.5 * radius * radius * (abs(theta) - math.sin(abs(theta)))
    return abs(theta) * radius, math.copysign(sector, theta)


def lwpolyline_metrics(points_with_bulge, closed):
    pts = [(p[0], p[1]) for p in points_with_bulge]
    bulges = [p[4] if len(p) > 4 else 0.0 for p in points_with_bulge]
    segments = list(zip(range(len(pts)), range(1, len(pts))))
    if closed and len(pts) >= 2:
        segments.append((len(pts) - 1, 0))
    length, bulge_area = 0.0, 0.0
    for i, j in segments:
        seg_len, seg_area = _bulge_arc(pts[i], pts[j], bulges[i])
        length += seg_len
        bulge_area += seg_area
    area = None
    if closed and len(pts) >= 2:
        shoelace = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1])) / 2.0
        area = abs(shoelace + bulge_area)
    return length, area


def describe(entity, full: bool = True) -> dict:
    """Normalised dict for one ezdxf entity; same keys as tools.query.describe_entity."""
    t = entity.dxftype()
    kind = t
    if t == "POLYLINE":
        kind = "POLYLINE3D" if entity.is_3d_polyline else "POLYLINE"
    dxf = entity.dxf
    info = {"handle": dxf.handle, "type": kind, "layer": dxf.get("layer", "0")}
    if full:
        info.update(object_name=DXF_TO_OBJECT.get(kind, t), color=dxf.get("color", 256),
                    linetype=dxf.get("linetype", "BYLAYER"), lineweight=dxf.get("lineweight", -1),
                    visible=not bool(dxf.get("invisible", 0)))
    if t == "LINE":
        start, end = _p3(dxf.start), _p3(dxf.end)
        info.update(points=[start, end], length=math.dist(start, end))
        if full:
            info["angle_degrees"] = math.degrees(math.atan2(end[1] - start[1], end[0] - start[0])) % 360.0
    elif t == "LWPOLYLINE":
        raw = [tuple(float(c) for c in p) for p in entity.get_points("xyseb")]
        length, area = lwpolyline_metrics(raw, entity.closed)
        info.update(points=[[p[0], p[1]] for p in raw[:MAX_VERTICES]], vertex_count=len(raw),
                    closed=bool(entity.closed), length=length)
        if any(p[4] for p in raw):
            info["has_bulges"] = True
        if area is not None:
            info["area"] = area
    elif t == "POLYLINE":
        pts = [_p3(v) for v in entity.points()]
        closed = bool(entity.is_closed)
        seq = pts + ([pts[0]] if closed and pts else [])
        info.update(points=pts[:MAX_VERTICES], vertex_count=len(pts), closed=closed,
                    length=sum(math.dist(a, b) for a, b in zip(seq, seq[1:])))
    elif t == "CIRCLE":
        info.update(center=_p3(dxf.center), radius=float(dxf.radius), area=math.pi * dxf.radius ** 2)
    elif t == "ARC":
        sweep = (dxf.end_angle - dxf.start_angle) % 360.0 or 360.0
        info.update(center=_p3(dxf.center), radius=float(dxf.radius), start_angle_degrees=float(dxf.start_angle),
                    end_angle_degrees=float(dxf.end_angle), length=math.radians(sweep) * dxf.radius)
    elif t in TEXT_TYPES:
        if t == "TEXT":
            info.update(text=dxf.text, insertion_point=_p3(dxf.insert), height=float(dxf.height))
        else:
            info.update(text=entity.text, insertion_point=_p3(dxf.insert), height=float(dxf.char_height))
            if full:
                info["width"] = float(dxf.get("width", 0.0))
        if full:
            info["rotation_degrees"] = float(dxf.get("rotation", 0.0))
    elif t == "INSERT":
        info.update(block=dxf.name, insertion_point=_p3(dxf.insert))
        if full:
            info.update(rotation_degrees=float(dxf.get("rotation", 0.0)),
                        scale=[dxf.get("xscale", 1.0), dxf.get("yscale", 1.0), dxf.get("zscale", 1.0)])
            if entity.attribs:
                info["attributes"] = {a.dxf.tag: a.dxf.text for a in entity.attribs}
    elif t == "HATCH":
        info["pattern"] = dxf.get("pattern_name")
        area = 0.0
        for path in entity.paths:
            vertices = getattr(path, "vertices", None)
            if vertices:
                pts = [(v[0], v[1]) for v in vertices]
                area += abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2.0
            else:
                area = None
                break
        info["area"] = area
    elif t == "DIMENSION":
        try:
            info["measurement"] = float(entity.get_measurement())
        except Exception:
            info["measurement"] = None
        if full:
            info["text_override"] = dxf.get("text", "")
    elif t == "ELLIPSE":
        major = _p3(dxf.major_axis)
        a = math.hypot(*major[:2])
        info.update(center=_p3(dxf.center), major_axis=major, ratio=float(dxf.ratio),
                    area=math.pi * a * a * dxf.ratio)
    if full or kind not in ("LINE", "LWPOLYLINE", "POLYLINE3D", "POLYLINE", "CIRCLE", "ARC"):
        info["bbox"] = _bbox(entity)
    return info


def _bbox(entity):
    from ezdxf import bbox

    try:
        box = bbox.extents([entity])
    except Exception:
        return None
    if not box.has_data:
        return None
    return [list(box.extmin), list(box.extmax)]


def snapshot_file(path: str, max_entities: int = 200000) -> dict:
    """Normalised snapshot of a DXF file's model space (read-only; recover mode)."""
    _require_ezdxf()
    from ezdxf import recover

    source = input_path(path, suffixes=(".dxf",))
    doc, auditor = recover.readfile(str(source))
    msp = doc.modelspace()
    entities = [describe(e, full=False) for i, e in enumerate(msp) if i < max_entities]
    code = int(doc.header.get("$INSUNITS", 0))
    return {"path": str(source), "entities": entities, "total": len(msp), "truncated": len(msp) > max_entities,
            "insunits": code, "audit": {"errors": len(auditor.errors), "fixes": len(auditor.fixes)},
            "dxf_version": doc.dxfversion}


def validate_file(path: str, max_messages: int = 50) -> dict:
    """Parse a DXF in recover mode and report what the auditor found."""
    _require_ezdxf()
    from ezdxf import recover

    source = input_path(path, suffixes=(".dxf",))
    doc, auditor = recover.readfile(str(source))
    msp = doc.modelspace()
    code = int(doc.header.get("$INSUNITS", 0))
    errors = [{"code": getattr(e, "code", None), "message": getattr(e, "message", str(e))} for e in auditor.errors]
    fixes = [{"code": getattr(f, "code", None), "message": getattr(f, "message", str(f))} for f in auditor.fixes]
    return {
        "status": "ok",
        "file": file_evidence(source),
        "dxf_version": doc.dxfversion,
        "insunits": code,
        "insunits_name": units.describe(code),
        "model_space_entities": len(msp),
        "counts_by_type": dict(Counter(describe(e, full=False)["type"] for e in msp).most_common()),
        "layer_count": len(doc.layers),
        "block_count": sum(1 for b in doc.blocks if not b.is_any_layout and not b.name.startswith("*")),
        "audit": {"error_count": len(errors), "fix_count": len(fixes), "errors": errors[:max_messages],
                  "fixes": fixes[:max_messages]},
        "valid": not errors,
        "message": f"{source.name}: {len(errors)} error(s), {len(fixes)} automatic fix(es) needed while reading.",
    }


class DxfBackend(Backend):
    name = "dxf"
    UNSUPPORTED_REASONS = {
        "launch_application": "the headless backend never starts AutoCAD",
        "create_test_drawing_with_line": "V0.1.0 live-AutoCAD fixture; use autocad_create_new_drawing + autocad_save_drawing",
        "highlight_entity": "highlighting is an AutoCAD display state; there is no display headlessly",
        "highlight_text_matches": "highlighting is an AutoCAD display state; there is no display headlessly",
        "query_and_highlight": "highlighting is an AutoCAD display state; there is no display headlessly",
        "plot_pdf": "plotting needs AutoCAD's plot engine; use autocad_render_preview headlessly",
    }

    def __init__(self):
        self._lock = threading.RLock()
        self._doc = None
        self._path: Path | None = None
        self._name: str | None = None
        self._dirty = False
        self._read_only = False
        self._counter = 0

    # ======= document state =======

    def _identity(self) -> str:
        if self._path is not None:
            return f"path:{str(self._path).lower()}"
        return f"unsaved:{self._name.lower()}"

    def _require_doc(self, *, write: bool):
        if self._doc is None:
            raise CadStateError("No drawing is open in the headless backend. Call autocad_create_new_drawing "
                                "or autocad_open_drawing first.", code="E_NO_ACTIVE_DOCUMENT")
        pinned = session.pinned_document()
        if pinned is not None and pinned != self._identity():
            raise CadStateError(
                f"The open drawing is {self._identity()!r}, but this session is pinned to {pinned!r}. "
                "Nothing was changed.", code="E_DOCUMENT_CHANGED",
                details={"pinned_document": pinned, "active_document": self._identity()})
        if write:
            self._apply_units_policy()
            self._dirty = True
        return self._doc

    def _apply_units_policy(self):
        preset = units.preset_name()
        header = self._doc.header
        changed = {}
        for name, value in units.preset_variables(preset):
            key = f"${name}"
            current = header.get(key)
            if current != value:
                header[key] = value
                changed[name] = {"from": current, "to": value}
        if changed:
            session.add_notice("units_changed", preset=preset, variables=changed)

    def _msp(self):
        return self._doc.modelspace()

    def _insunits(self) -> int:
        return int(self._doc.header.get("$INSUNITS", 0))

    def _entity(self, handle: str):
        handle = geometry.validate_handle(handle)
        entity = self._doc.entitydb.get(handle.upper())
        if entity is None or not entity.is_alive or entity.dxf.owner != self._msp().layout_key:
            raise CadStateError(f"No model-space entity with handle {handle!r}.", code="E_ENTITY_NOT_FOUND",
                                details={"handle": handle})
        return entity

    def _result(self, **fields):
        fields.setdefault("status", "ok")
        fields["drawing_identity"] = self._identity()
        return fields

    def _run(self, func):
        with self._lock:
            result, notices = session.collect(func)
        if isinstance(result, dict):
            result.setdefault("backend", self.name)
            if notices:
                result["notices"] = notices
        return result

    # ======= session / documents =======

    def get_status(self):
        version = ezdxf_version()
        doc = None
        if self._doc is not None:
            doc = {"identity": self._identity(), "unsaved_changes": self._dirty, "read_only": self._read_only}
        return {
            "backend": self.name, "installed": version is not None, "running": version is not None,
            "connected": version is not None, "supported": version is not None, "version": version,
            "release_year": None, "document": doc,
            "message": (f"Headless DXF backend (ezdxf {version}); no AutoCAD process is used."
                        if version else 'Headless DXF backend selected but ezdxf is not installed: pip install -e ".[dxf]"'),
        }

    def active_drawing_identity(self):
        return self._identity() if self._doc is not None else None

    def _refuse_switch(self, target_identity, pin):
        pinned = session.pinned_document()
        if pinned is not None and not pin and target_identity != pinned:
            raise CadStateError(f"This session is pinned to {pinned!r}; pass pin=true to move the pin, or unpin first.",
                                code="E_DOCUMENT_PINNED", details={"pinned_document": pinned})
        if self._doc is not None and self._dirty:
            raise CadStateError(
                f"The open drawing {self._identity()!r} has unsaved changes and the headless backend holds one "
                "drawing at a time; save it or close it with discard_changes=true first.",
                code="E_UNSAVED_CHANGES", details={"identity": self._identity()})
        return pinned

    def create_new_drawing(self, template=None, pin=False):
        def run():
            ezdxf = _require_ezdxf()
            self._counter += 1
            name = f"Drawing{self._counter}.dxf"
            previous_pin = self._refuse_switch(f"unsaved:{name.lower()}", pin)
            if template is not None:
                source = input_path(template, suffixes=(".dxf",))
                doc = ezdxf.readfile(str(source))
            else:
                doc = ezdxf.new("R2018", setup=True)
            self._doc, self._path, self._name, self._dirty, self._read_only = doc, None, name, False, False
            self._apply_units_policy()
            if pin:
                session.pin_document(self._identity())
            return self._result(drawing_name=name, saved=False, pinned=bool(pin), previous_pin=previous_pin,
                                verified=True, verification="new_document_created",
                                message=f"Created new headless drawing {name!r}.")
        return self._run(run)

    def open_drawing(self, path, read_only=True, pin=False):
        def run():
            ezdxf = _require_ezdxf()
            if str(path).lower().endswith(".dwg"):
                raise self._unsupported_reason("open_drawing", "ezdxf reads DXF only; export the DWG to DXF with "
                                               "AutoCAD (autocad_export_dxf on the live backend) or the ODA File Converter")
            source = input_path(path, suffixes=(".dxf",))
            identity = f"path:{str(source).lower()}"
            previous_pin = self._refuse_switch(identity, pin)
            from ezdxf import recover

            doc, auditor = recover.readfile(str(source))
            self._doc, self._path, self._name = doc, source, source.name
            self._dirty, self._read_only = False, bool(read_only)
            if pin:
                session.pin_document(self._identity())
            return self._result(
                name=source.name, path=str(source), read_only=self._read_only, dxf_version=doc.dxfversion,
                audit={"errors": len(auditor.errors), "fixes": len(auditor.fixes)},
                pinned=bool(pin), previous_pin=previous_pin, verified=True,
                verification="dxf_parsed_with_recover_mode",
                message=f"Opened {source.name} ({len(doc.modelspace())} model-space entities)"
                        + (" read-only." if read_only else "."))
        return self._run(run)

    def _unsupported_reason(self, operation, reason):
        from core.errors import UnsupportedOperationError

        return UnsupportedOperationError(operation, self.name, reason)

    def save_drawing(self, path=None, overwrite=False, format="dwg", version=None):
        def run():
            fmt = (format or "").lower()
            if fmt == "dwg" and path is not None and str(path).lower().endswith(".dwg"):
                raise self._unsupported_reason("save_drawing", "ezdxf cannot write DWG; save as .dxf")
            doc = self._require_doc(write=False)
            if version is not None and DXF_VERSIONS.get(version) != doc.dxfversion:
                raise self._unsupported_reason(
                    "save_drawing", f"the headless backend saves in the document's own DXF version "
                    f"({doc.dxfversion}); converting to {version} is not supported")
            before = self._identity()
            if path is None:
                if self._path is None:
                    raise CadError("This drawing has never been saved; pass path to choose a file.", code="E_INVALID_INPUT")
                if self._read_only:
                    raise CadError("This drawing was opened read-only; pass a new path to save a copy.",
                                   code="E_INVALID_INPUT")
                target = self._path
            else:
                target = output_path(path, suffixes=(".dxf",), overwrite=True)
                same = self._path is not None and str(target).lower() == str(self._path).lower()
                if target.exists() and not same and not overwrite:
                    raise CadError(f"{target} already exists; pass overwrite=true to replace it",
                                   code="E_OUTPUT_EXISTS", details={"path": str(target)})
                if same and self._read_only:
                    raise CadError("This drawing was opened read-only; it cannot be saved over its source.",
                                   code="E_INVALID_INPUT")
            temp = target.with_name(f".{target.stem}.{uuid.uuid4().hex[:8]}.dxf")
            doc.saveas(str(temp))
            os.replace(temp, target)
            self._path, self._name, self._dirty = target, target.name, False
            if path is not None:
                self._read_only = False
            pin_moved = None
            if session.pinned_document() == before and self._identity() != before:
                session.pin_document(self._identity())
                pin_moved = {"from": before, "to": self._identity()}
            import ezdxf

            reread = ezdxf.readfile(str(target))
            return self._result(format="dxf", version=doc.dxfversion, file=file_evidence(target),
                                identity_before=before, pin_moved=pin_moved, unsaved_changes=False, saved=True,
                                verified=len(reread.modelspace()) == len(doc.modelspace()),
                                verification="file_re_read_with_same_entity_count",
                                message=f"Saved {target.name}.")
        return self._run(run)

    def close_drawing(self, identity=None, discard_changes=False):
        def run():
            if self._doc is None:
                raise CadError("No drawing is open.", code="E_NO_ACTIVE_DOCUMENT")
            current = self._identity()
            if identity is not None and identity != current:
                raise CadError(f"No open drawing has identity {identity!r}.", code="E_DOCUMENT_NOT_FOUND",
                               details={"open": [current]})
            if self._dirty and not discard_changes:
                raise CadError(f"{self._name} has unsaved changes; save it first or pass discard_changes=true.",
                               code="E_UNSAVED_CHANGES", details={"identity": current})
            discarded = self._dirty
            self._doc, self._path, self._name, self._dirty = None, None, None, False
            unpinned = session.pinned_document() == current
            if unpinned:
                session.unpin_document()
            return {"status": "ok", "closed": {"identity": current}, "discarded_changes": discarded,
                    "unpinned": unpinned, "open_drawings": [], "verified": True,
                    "verification": "document_released", "message": f"Closed {current}."}
        return self._run(run)

    def list_drawings(self):
        def run():
            rows = []
            if self._doc is not None:
                rows.append({"name": self._name, "identity": self._identity(),
                             "path": str(self._path) if self._path else None, "saved_to_disk": self._path is not None,
                             "unsaved_changes": self._dirty, "read_only": self._read_only, "active": True})
            return {"status": "ok", "count": len(rows), "drawings": rows,
                    "pinned_document": session.pinned_document(),
                    "message": f"{len(rows)} drawing(s) open (the headless backend holds at most one)."}
        return self._run(run)

    def activate_drawing(self, identity, pin=False):
        def run():
            if self._doc is None or identity != self._identity():
                raise CadError(f"No open drawing has identity {identity!r}.", code="E_DOCUMENT_NOT_FOUND")
            if pin:
                session.pin_document(identity)
            return self._result(pinned=bool(pin), verified=True, verification="single_document",
                                message="The headless backend holds one drawing; it is already active.")
        return self._run(run)

    def set_drawing_units(self, preset):
        def run():
            key = (preset or "").strip().lower()
            if key not in units.UNIT_PRESETS:
                raise CadError(f"preset must be one of {sorted(units.UNIT_PRESETS)}, got {preset!r}",
                               code="E_INVALID_INPUT")
            doc = self._require_doc(write=False)
            changed = {}
            for name, value in units.preset_variables(key):
                current = doc.header.get(f"${name}")
                if current != value:
                    doc.header[f"${name}"] = value
                    changed[name] = {"from": current, "to": value}
            if changed:
                self._dirty = True
            session.set_units_override(key)
            code = self._insunits()
            return self._result(preset=key, changed=changed, failed={}, insunits=code,
                                insunits_name=units.describe(code), session_preset=key, verified=True,
                                verification="header_variables_set",
                                message=f"Applied units preset {key!r}.")
        return self._run(run)

    # ======= primitives =======

    def _layer(self, doc, name):
        if name is None:
            return "0"
        name = geometry.validate_layer_name(name)
        if name not in doc.layers:
            doc.layers.add(name)
        return name

    def _created(self, entity, message, **fields):
        return self._result(handle=entity.dxf.handle, layer=entity.dxf.layer, verified=True,
                            verification="entity_in_modelspace", message=message, **fields)

    def draw_line(self, start_point, end_point, layer=None):
        start = geometry.validate_point_2d_or_3d(start_point, "start_point")
        end = geometry.validate_point_2d_or_3d(end_point, "end_point")

        def run():
            doc = self._require_doc(write=True)
            e = self._msp().add_line(start, end, dxfattribs={"layer": self._layer(doc, layer)})
            return self._created(e, f"Created line {e.dxf.handle} from {start} to {end}.", start_point=start,
                                 end_point=end)
        return self._run(run)

    def draw_polyline(self, points, closed=False, layer=None):
        pts = geometry.validate_points(points, "points")

        def run():
            doc = self._require_doc(write=True)
            e = self._msp().add_polyline3d(pts, close=closed, dxfattribs={"layer": self._layer(doc, layer)})
            return self._created(e, f"Created polyline {e.dxf.handle} with {len(pts)} points.", points=pts,
                                 closed=bool(closed))
        return self._run(run)

    def draw_rectangle(self, corner1=None, corner2=None, base_point=None, width=None, height=None, layer=None):
        by_corners = corner1 is not None and corner2 is not None
        by_size = base_point is not None and width is not None and height is not None
        if by_corners == by_size:
            raise geometry.ValidationError("draw_rectangle needs exactly one of: (corner1 and corner2), or "
                                           "(base_point and width and height)")
        if by_corners:
            c1 = geometry.validate_point_2d_or_3d(corner1, "corner1")
            c2 = geometry.validate_point_2d_or_3d(corner2, "corner2")
            if c1[2] != c2[2]:
                raise geometry.ValidationError(f"corner1 and corner2 must lie in the same z-plane, got z={c1[2]} and z={c2[2]}")
            (x1, y1, z), (x2, y2, _) = c1, c2
        else:
            x1, y1, z = geometry.validate_point_2d_or_3d(base_point, "base_point")
            x2 = x1 + geometry.validate_positive(width, "width")
            y2 = y1 + geometry.validate_positive(height, "height")
        return self.draw_polyline([(x1, y1, z), (x2, y1, z), (x2, y2, z), (x1, y2, z)], closed=True, layer=layer)

    def draw_circle(self, center, radius, layer=None):
        c = geometry.validate_point_2d_or_3d(center, "center")
        r = geometry.validate_radius(radius)

        def run():
            doc = self._require_doc(write=True)
            e = self._msp().add_circle(c, r, dxfattribs={"layer": self._layer(doc, layer)})
            return self._created(e, f"Created circle {e.dxf.handle} at {c} with radius {r}.", center=c, radius=r)
        return self._run(run)

    def draw_text(self, text, insertion_point, height, rotation_degrees=0.0, layer=None):
        text = geometry.validate_text(text)
        p = geometry.validate_point_2d_or_3d(insertion_point, "insertion_point")
        h = geometry.validate_positive(height, "height")
        rot = geometry.validate_angle_degrees(rotation_degrees, "rotation_degrees")

        def run():
            doc = self._require_doc(write=True)
            e = self._msp().add_text(text, height=h, rotation=rot, dxfattribs={"layer": self._layer(doc, layer)})
            e.set_placement(p)
            return self._created(e, f"Created text {e.dxf.handle} at {p}.", text=text, insertion_point=p,
                                 height=h, rotation_degrees=rot)
        return self._run(run)

    def draw_arc(self, center, radius, start_angle_degrees, end_angle_degrees, layer=None):
        c = geometry.validate_point_2d_or_3d(center, "center")
        r = geometry.validate_radius(radius)
        a0 = geometry.validate_angle_degrees(start_angle_degrees, "start_angle_degrees")
        a1 = geometry.validate_angle_degrees(end_angle_degrees, "end_angle_degrees")
        if math.isclose(a0 % 360.0, a1 % 360.0, abs_tol=1e-6):
            raise geometry.ValidationError("start and end angles must differ (use autocad_draw_circle for a full circle)")

        def run():
            doc = self._require_doc(write=True)
            e = self._msp().add_arc(c, r, a0, a1, dxfattribs={"layer": self._layer(doc, layer)})
            sweep = (a1 - a0) % 360.0
            return self._created(e, f"Created arc r={r:g}.", center=c, radius=r,
                                 start_angle_degrees=e.dxf.start_angle, end_angle_degrees=e.dxf.end_angle,
                                 arc_length=math.radians(sweep) * r)
        return self._run(run)

    def draw_mtext(self, text, insertion_point, height, width=0.0, rotation_degrees=0.0, layer=None):
        text = geometry.validate_text(text)
        if not text:
            raise geometry.ValidationError("text must not be empty")
        p = geometry.validate_point_2d_or_3d(insertion_point, "insertion_point")
        h = geometry.validate_positive(height, "height")
        w = geometry.validate_number(width, "width")
        if w < 0:
            raise geometry.ValidationError("width must be >= 0")
        rot = geometry.validate_angle_degrees(rotation_degrees, "rotation_degrees")

        def run():
            doc = self._require_doc(write=True)
            e = self._msp().add_mtext(text, dxfattribs={"layer": self._layer(doc, layer), "char_height": h,
                                                        "width": w, "rotation": rot})
            e.set_location(p)
            return self._created(e, "Created MTEXT.", text=text, insertion_point=p, height=h, width=w,
                                 rotation_degrees=rot)
        return self._run(run)

    # ======= layers =======

    def create_layer(self, name, color_index=None, linetype=None):
        name = geometry.validate_layer_name(name)
        if color_index is not None:
            color_index = geometry.validate_color_index(color_index)

        def run():
            doc = self._require_doc(write=True)
            existed = name in doc.layers
            layer = doc.layers.get(name) if existed else doc.layers.add(name)
            if color_index is not None:
                layer.color = color_index
            if linetype is not None:
                if linetype not in doc.linetypes:
                    raise geometry.ValidationError(f"linetype {linetype!r} is not defined in this DXF")
                layer.dxf.linetype = linetype
            return self._result(layer_name=name, created=not existed, color_index=layer.color,
                                linetype=layer.dxf.linetype, verified=True, verification="layer_table_entry",
                                message=f"Layer {name!r} {'created' if not existed else 'updated'}.")
        return self._run(run)

    def ensure_layer(self, name, color_index=None, linetype=None):
        standard = ARCHITECTURAL_LAYERS.get(name)
        if standard is not None:
            color_index = standard["color_index"] if color_index is None else color_index
            linetype = standard["linetype"] if linetype is None else linetype
        return self.create_layer(name, color_index=color_index, linetype=linetype)

    def list_layers(self):
        def run():
            doc = self._require_doc(write=False)
            current = doc.header.get("$CLAYER", "0")
            rows = [{"name": layer.dxf.name, "on": layer.is_on(), "frozen": layer.is_frozen(),
                     "locked": layer.is_locked(), "color_index": abs(layer.color), "linetype": layer.dxf.linetype,
                     "lineweight": layer.dxf.get("lineweight", -3), "plottable": bool(layer.dxf.get("plot", 1)),
                     "current": layer.dxf.name == current} for layer in doc.layers]
            return self._result(count=len(rows), layers=rows, current_layer=current)
        return self._run(run)

    def set_layer_properties(self, name, on=None, frozen=None, locked=None, color_index=None, linetype=None,
                             lineweight=None, plottable=None):
        from utils.validation import LAYER_LINEWEIGHTS

        name = geometry.validate_layer_name(name)
        if color_index is not None:
            color_index = geometry.validate_color_index(color_index, "color_index")
        if lineweight is not None and lineweight not in LAYER_LINEWEIGHTS:
            raise geometry.ValidationError(f"lineweight must be one of {sorted(LAYER_LINEWEIGHTS)}")
        if all(v is None for v in (on, frozen, locked, color_index, linetype, lineweight, plottable)):
            raise geometry.ValidationError("give at least one property to change")

        def run():
            doc = self._require_doc(write=True)
            if name not in doc.layers:
                raise CadStateError(f"Layer {name!r} does not exist.", code="E_LAYER_NOT_FOUND")
            layer = doc.layers.get(name)
            if frozen and doc.header.get("$CLAYER", "0").lower() == name.lower():
                raise geometry.ValidationError(f"{name!r} is the current layer, which cannot be frozen")
            if on is not None:
                layer.on() if on else layer.off()
            if frozen is not None:
                layer.freeze() if frozen else layer.thaw()
            if locked is not None:
                layer.lock() if locked else layer.unlock()
            if color_index is not None:
                layer.color = color_index
            if linetype is not None:
                if linetype not in doc.linetypes:
                    raise geometry.ValidationError(f"linetype {linetype!r} is not defined in this DXF")
                layer.dxf.linetype = linetype
            if lineweight is not None:
                layer.dxf.lineweight = lineweight
            if plottable is not None:
                layer.dxf.plot = int(plottable)
            after = {"on": layer.is_on(), "frozen": layer.is_frozen(), "locked": layer.is_locked(),
                     "color_index": abs(layer.color), "linetype": layer.dxf.linetype,
                     "lineweight": layer.dxf.get("lineweight", -3), "plottable": bool(layer.dxf.get("plot", 1))}
            return self._result(layer_name=name, after=after, verified=True, verification="layer_table_entry",
                                mismatched={}, message=f"Layer {name!r} updated.")
        return self._run(run)

    # ======= editing =======

    def _transform(self, handle, matrix_fn, message, **fields):
        def run():
            self._require_doc(write=True)
            entity = self._entity(handle)
            entity.transform(matrix_fn())
            return self._result(handle=entity.dxf.handle, verified=True, verification="entity_transformed",
                                message=message, **fields)
        return self._run(run)

    def move_entity(self, handle, displacement):
        from ezdxf.math import Matrix44

        disp = geometry.validate_displacement(displacement)
        return self._transform(handle, lambda: Matrix44.translate(*disp), f"Moved entity {handle} by {disp}.",
                               displacement=disp)

    def rotate_entity(self, handle, base_point, angle_degrees):
        from ezdxf.math import Matrix44

        base = geometry.validate_point_2d_or_3d(base_point, "base_point")
        angle = geometry.validate_angle_degrees(angle_degrees)

        def matrix():
            return (Matrix44.translate(-base[0], -base[1], -base[2]) @ Matrix44.z_rotate(math.radians(angle))
                    @ Matrix44.translate(*base))
        return self._transform(handle, matrix, f"Rotated entity {handle} by {angle} degrees about {base}.",
                               base_point=base, angle_degrees=angle,
                               angle_convention="counterclockwise-positive, viewed from +Z")

    def scale_entity(self, handle, base_point, factor):
        from ezdxf.math import Matrix44

        base = geometry.validate_point_2d_or_3d(base_point, "base_point")
        factor = geometry.validate_positive(factor, "factor")

        def matrix():
            return (Matrix44.translate(-base[0], -base[1], -base[2]) @ Matrix44.scale(factor)
                    @ Matrix44.translate(*base))
        return self._transform(handle, matrix, f"Scaled {handle} by {factor:g}.", base_point=base, factor=factor)

    def _copy(self, entity):
        clone = entity.copy()
        self._msp().add_entity(clone)
        return clone

    def copy_entity(self, handle, displacement):
        disp = geometry.validate_displacement(displacement)

        def run():
            self._require_doc(write=True)
            entity = self._entity(handle)
            before = len(self._msp())
            clone = self._copy(entity)
            clone.translate(*disp)
            if len(self._msp()) != before + 1:
                raise VerificationError("Copy could not be verified.")
            return self._result(source_handle=handle, new_handle=clone.dxf.handle, displacement=disp,
                                verified=True, verification="modelspace_count_plus_one_and_new_handle",
                                message=f"Copied entity {handle} to new entity {clone.dxf.handle}.")
        return self._run(run)

    def mirror_entity(self, handle, axis_start, axis_end, keep_original=True):
        from ezdxf.math import Matrix44

        p1 = geometry.validate_point_2d_or_3d(axis_start, "axis_start")
        p2 = geometry.validate_point_2d_or_3d(axis_end, "axis_end")
        if p1[:2] == p2[:2]:
            raise geometry.ValidationError("axis_start and axis_end must be different points")

        def run():
            self._require_doc(write=True)
            entity = self._entity(handle)
            angle = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
            m = (Matrix44.translate(-p1[0], -p1[1], 0) @ Matrix44.z_rotate(-angle) @ Matrix44.scale(1, -1, 1)
                 @ Matrix44.z_rotate(angle) @ Matrix44.translate(p1[0], p1[1], 0))
            clone = self._copy(entity)
            clone.transform(m)
            if not keep_original:
                self._msp().delete_entity(entity)
            return self._result(source_handle=handle, new_handle=clone.dxf.handle, original_kept=keep_original,
                                axis=[p1, p2], verified=True, verification="mirrored_copy_created",
                                message=f"Mirrored {handle} to {clone.dxf.handle}.")
        return self._run(run)

    def offset_entity(self, handle, distance):
        distance = geometry.validate_number(distance, "distance")
        if distance == 0:
            raise geometry.ValidationError("distance must not be zero")

        def run():
            from ezdxf.math import offset_vertices_2d

            self._require_doc(write=True)
            entity = self._entity(handle)
            t = entity.dxftype()
            clone = self._copy(entity)
            if t in ("CIRCLE", "ARC"):
                new_radius = clone.dxf.radius + distance
                if new_radius <= 0:
                    self._msp().delete_entity(clone)
                    raise geometry.ValidationError(f"offset would give a non-positive radius ({new_radius})")
                clone.dxf.radius = new_radius
            elif t == "LINE":
                (x1, y1, _), (x2, y2, _) = _p3(clone.dxf.start), _p3(clone.dxf.end)
                length = math.hypot(x2 - x1, y2 - y1)
                nx, ny = -(y2 - y1) / length * distance, (x2 - x1) / length * distance
                clone.translate(nx, ny, 0)
            elif t == "LWPOLYLINE" and not any(p[4] for p in entity.get_points("xyseb")):
                pts = [(p[0], p[1]) for p in entity.get_points("xy")]
                clone.set_points(list(offset_vertices_2d(pts, offset=distance, closed=entity.closed)), format="xy")
            else:
                self._msp().delete_entity(clone)
                raise self._unsupported_reason("offset_entity", f"headless offset supports LINE, CIRCLE, ARC and "
                                               f"bulge-free LWPOLYLINE, not {t}")
            return self._result(source_handle=handle, distance=distance, new_handles=[clone.dxf.handle],
                                verified=True, verification="offset_copy_created",
                                message=f"Offset {handle} by {distance:g}.")
        return self._run(run)

    def array_rectangular(self, handle, rows, columns, row_spacing, column_spacing):
        for label, value in (("rows", rows), ("columns", columns)):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1000:
                raise geometry.ValidationError(f"{label} must be an integer from 1 to 1000, got {value!r}")
        if rows * columns < 2 or rows * columns > 10000:
            raise geometry.ValidationError("rows x columns must be between 2 and 10000")
        row_spacing = geometry.validate_number(row_spacing, "row_spacing")
        column_spacing = geometry.validate_number(column_spacing, "column_spacing")

        def run():
            self._require_doc(write=True)
            entity = self._entity(handle)
            handles = []
            for r in range(rows):
                for c in range(columns):
                    if r == 0 and c == 0:
                        continue
                    clone = self._copy(entity)
                    clone.translate(c * column_spacing, r * row_spacing, 0)
                    handles.append(clone.dxf.handle)
            return self._result(source_handle=handle, rows=rows, columns=columns, row_spacing=row_spacing,
                                column_spacing=column_spacing, new_handles=handles, verified=True,
                                verification="copy_count", message=f"Arrayed {handle} into {rows}x{columns}.")
        return self._run(run)

    def delete_entities(self, handles, dry_run=True):
        from utils.validation import validate_handles

        handles = validate_handles(handles)

        def run():
            self._require_doc(write=not dry_run)
            found, missing = [], []
            for h in handles:
                try:
                    found.append(self._entity(h))
                except CadError:
                    missing.append(h)
            plan = [{"handle": e.dxf.handle, "type": describe(e, full=False)["type"], "layer": e.dxf.layer}
                    for e in found]
            if dry_run:
                return self._result(dry_run=True, would_delete=plan, not_found=missing,
                                    message=f"Dry run: {len(plan)} entity(ies) would be deleted.")
            before = len(self._msp())
            for e in found:
                self._msp().delete_entity(e)
            after = len(self._msp())
            return self._result(dry_run=False, deleted=plan, failed=[], not_found=missing,
                                modelspace_count={"before": before, "after": after},
                                verified=after == before - len(found), verification="modelspace_count",
                                still_resolving=[], message=f"Deleted {len(found)} entity(ies).")
        return self._run(run)

    def set_entity_properties(self, handles, layer=None, color_index=None, linetype=None, lineweight=None):
        from utils.validation import VALID_LINEWEIGHTS, validate_color_for_entity, validate_handles

        handles = validate_handles(handles)
        if layer is None and color_index is None and linetype is None and lineweight is None:
            raise geometry.ValidationError("give at least one of layer, color_index, linetype, lineweight")
        if color_index is not None:
            color_index = validate_color_for_entity(color_index)
        if lineweight is not None and lineweight not in VALID_LINEWEIGHTS:
            raise geometry.ValidationError(f"lineweight must be one of {sorted(VALID_LINEWEIGHTS)}")

        def run():
            doc = self._require_doc(write=True)
            if layer is not None:
                self._layer(doc, layer)
            if linetype is not None and linetype not in doc.linetypes:
                raise geometry.ValidationError(f"linetype {linetype!r} is not defined in this DXF")
            changed, missing = [], []
            for h in handles:
                try:
                    e = self._entity(h)
                except CadError:
                    missing.append(h)
                    continue
                if layer is not None:
                    e.dxf.layer = layer
                if color_index is not None:
                    e.dxf.color = color_index
                if linetype is not None:
                    e.dxf.linetype = linetype
                if lineweight is not None:
                    e.dxf.lineweight = lineweight
                changed.append(h)
            wanted = {k: v for k, v in (("layer", layer), ("color", color_index), ("linetype", linetype),
                                        ("lineweight", lineweight)) if v is not None}
            return self._result(changed=changed, not_found=missing, properties=wanted, mismatched=[],
                                verified=bool(changed), verification="dxf_attributes_set",
                                message=f"Updated {len(changed)} entity(ies).")
        return self._run(run)

    # ======= query =======

    def _iter(self, max_entities):
        for i, e in enumerate(self._msp()):
            if i >= max_entities:
                break
            yield e

    def drawing_summary(self, max_entities=20000):
        max_entities = validate_limit(max_entities, default=20000, maximum=500000, label="max_entities")

        def run():
            doc = self._require_doc(write=False)
            msp = self._msp()
            total = len(msp)
            by_type, by_layer = Counter(), Counter()
            for e in self._iter(max_entities):
                by_type[describe(e, full=False)["type"]] += 1
                by_layer[e.dxf.get("layer", "0")] += 1
            code = self._insunits()
            extents = None
            try:
                from ezdxf import bbox

                box = bbox.extents(msp)
                if box.has_data:
                    extents = {"min": list(box.extmin), "max": list(box.extmax)}
            except Exception:
                pass
            blocks = sorted(b.name for b in doc.blocks if not b.is_any_layout and not b.name.startswith("*"))
            return self._result(
                name=self._name, saved_to_disk=self._path is not None, unsaved_changes=self._dirty,
                read_only=self._read_only,
                units={"insunits": code, "insunits_name": units.describe(code), "lunits": doc.header.get("$LUNITS"),
                       "measurement": {0: "imperial", 1: "metric"}.get(doc.header.get("$MEASUREMENT"))},
                extents=extents, model_space_entities=total,
                paper_space_entities=sum(len(lo) for lo in doc.layouts if lo.name != "Model"),
                scanned_entities=min(total, max_entities), truncated=total > max_entities,
                counts_by_type=dict(by_type.most_common()), counts_by_layer=dict(by_layer.most_common()),
                layer_count=len(doc.layers), layers=[layer.dxf.name for layer in doc.layers][:200],
                layers_truncated=len(doc.layers) > 200, current_layer=doc.header.get("$CLAYER", "0"),
                blocks=blocks[:200], block_count=len(blocks), layouts=[lo.name for lo in doc.layouts],
                dxf_version=doc.dxfversion, message=f"{total} model-space entities on {len(doc.layers)} layers.")
        return self._run(run)

    def list_entities(self, entity_types=None, layers=None, bbox=None, offset=0, limit=100, include_bbox=False,
                      max_entities=20000):
        from utils.validation import box_inside as _inside
        from utils.validation import validate_bbox, validate_entity_types, validate_layer_filter

        wanted_types = validate_entity_types(entity_types)
        wanted_layers = validate_layer_filter(layers)
        window = validate_bbox(bbox)
        offset = validate_offset(offset)
        limit = validate_limit(limit, default=100, maximum=5000)
        max_entities = validate_limit(max_entities, default=20000, maximum=500000, label="max_entities")

        def run():
            self._require_doc(write=False)
            rows = []
            for e in self._iter(max_entities):
                kind = describe(e, full=False)["type"]
                if wanted_types is not None and kind not in wanted_types:
                    continue
                layer = e.dxf.get("layer", "0")
                if wanted_layers is not None and layer.lower() not in wanted_layers:
                    continue
                box = _bbox(e) if (window is not None or include_bbox) else None
                if window is not None and (box is None or not _inside(box, window)):
                    continue
                row = {"handle": e.dxf.handle, "type": kind, "layer": layer}
                if include_bbox:
                    row["bbox"] = box
                rows.append(row)
            total_in_space = len(self._msp())
            window_page = page(rows, offset=offset, limit=limit)
            return self._result(entities=window_page.pop("items"), **window_page,
                                scanned_entities=min(total_in_space, max_entities),
                                scan_truncated=total_in_space > max_entities,
                                filters={"entity_types": sorted(wanted_types) if wanted_types else None,
                                         "layers": layers, "bbox": bbox},
                                message=f"{window_page['total']} matching entities; returned {window_page['returned']}.")
        return self._run(run)

    def get_entity(self, handle):
        def run():
            self._require_doc(write=False)
            return self._result(entity=describe(self._entity(handle)))
        return self._run(run)

    def snapshot_entities(self, max_entities=20000):
        max_entities = validate_limit(max_entities, default=20000, maximum=500000, label="max_entities")

        def run():
            doc = self._require_doc(write=False)
            code = self._insunits()
            total = len(self._msp())
            return {"drawing_identity": self._identity(),
                    "units": {"insunits": code, "insunits_name": units.describe(code),
                              "lunits": doc.header.get("$LUNITS"),
                              "measurement": {0: "imperial", 1: "metric"}.get(doc.header.get("$MEASUREMENT"))},
                    "entities": [describe(e, full=False) for e in self._iter(max_entities)],
                    "total": total, "truncated": total > max_entities}
        return self._run(run)

    def scan_all_entities(self):
        import db

        def run():
            self._require_doc(write=False)
            entities, skipped = [], 0
            for e in self._msp():
                info = describe(e, full=False)
                kind = info["type"]
                if kind == "LINE":
                    props = {"start_point": info["points"][0], "end_point": info["points"][1]}
                elif kind == "CIRCLE":
                    props = {"center": info["center"], "radius": info["radius"]}
                elif kind in ("POLYLINE3D", "LWPOLYLINE"):
                    props = {"vertex_count": info["vertex_count"], "closed": info["closed"]}
                elif kind in TEXT_TYPES:
                    props = {"text": info["text"], "insertion_point": info["insertion_point"], "height": info["height"]}
                else:
                    props = {}
                entities.append({"handle": e.dxf.handle, "object_name": DXF_TO_OBJECT.get(kind, e.dxftype()),
                                 "layer": e.dxf.get("layer", "0"), "properties": props})
            db_path = get_db_path()
            with db.connection(db_path) as conn:
                drawing_id = db.upsert_drawing(conn, self._identity(), self._name,
                                               str(self._path) if self._path else None, self._path is not None)
                db.replace_drawing_entities(conn, drawing_id, entities)
            return self._result(scanned_count=len(entities), skipped_count=skipped,
                                entity_type_counts=dict(Counter(x["object_name"] for x in entities)), db_path=db_path,
                                scope_note="top-level model-space entities only; block contents and paper space are not scanned.",
                                message=f"Scanned {len(entities)} entities into {db_path}.")
        return self._run(run)

    def count_text_patterns(self, pattern, use_regex=False, limit=500):
        pattern = geometry.validate_text(pattern, "pattern")
        if not pattern:
            raise geometry.ValidationError("pattern must not be empty")
        limit = validate_limit(limit, default=500, maximum=10000)
        compiled = None
        if use_regex:
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise geometry.ValidationError(f"pattern is not a valid regex: {exc}") from exc

        def run():
            self._require_doc(write=False)
            matches = []
            for e in self._msp().query("TEXT MTEXT"):
                text = e.dxf.text if e.dxftype() == "TEXT" else e.text
                if (compiled.search(text) if compiled else pattern in text):
                    matches.append({"handle": e.dxf.handle, "text": text, "layer": e.dxf.layer})
            return self._result(pattern=pattern, use_regex=use_regex, match_count=len(matches),
                                matches=matches[:limit], truncated=len(matches) > limit,
                                message=f"{len(matches)} text entity(ies) match {pattern!r}.")
        return self._run(run)

    # ======= annotation =======

    def add_dimension(self, kind, first_point, second_point, dimension_line_point, rotation_degrees=0.0,
                      text_override=None, layer=None):
        from domain.architecture import Primitive
        from utils.validation import DIMENSION_KINDS

        if kind not in DIMENSION_KINDS:
            raise geometry.ValidationError(f"kind must be one of {list(DIMENSION_KINDS)}, got {kind!r}")
        p1 = geometry.validate_point_2d_or_3d(first_point, "first_point")
        p2 = geometry.validate_point_2d_or_3d(second_point, "second_point")
        loc = geometry.validate_point_2d_or_3d(dimension_line_point, "dimension_line_point")
        if p1[:2] == p2[:2]:
            raise geometry.ValidationError("first_point and second_point must differ")
        rotation = geometry.validate_angle_degrees(rotation_degrees, "rotation_degrees")
        if text_override is not None:
            text_override = geometry.validate_text(text_override, "text_override")

        def run():
            from backends.targets import DxfTarget

            doc = self._require_doc(write=True)
            name = self._layer(doc, layer)
            prim = Primitive("dim_aligned" if kind == "aligned" else "dim_linear", name, "dim", points=(p1, p2),
                             location=loc, rotation=rotation)
            handle = DxfTarget(doc).draw(prim)
            dim = doc.entitydb.get(handle)
            if text_override is not None:
                dim.dxf.text = text_override
            measurement = float(dim.get_measurement())
            if kind == "aligned":
                expected = math.dist(p1[:2], p2[:2])
            else:
                a = math.radians(rotation)
                expected = abs((p2[0] - p1[0]) * math.cos(a) + (p2[1] - p1[1]) * math.sin(a))
            if not math.isclose(measurement, expected, rel_tol=1e-6, abs_tol=1e-9):
                raise VerificationError(f"Dimension measures {measurement}, expected {expected}.")
            return self._result(handle=handle, layer=name, kind=kind, measurement=measurement,
                                expected_measurement=expected, text_override=text_override, verified=True,
                                verification="measurement_matches_geometry",
                                message=f"Created {kind} dimension measuring {measurement}.")
        return self._run(run)

    def add_hatch(self, boundary_handles=None, boundary_points=None, pattern="ANSI31", scale=1.0, angle_degrees=0.0,
                  layer=None, keep_boundary=True):
        if (boundary_handles is None) == (boundary_points is None):
            raise geometry.ValidationError("give exactly one of boundary_handles or boundary_points")
        if not isinstance(pattern, str) or not pattern.strip() or any(c in pattern for c in ' \t\n;"'):
            raise geometry.ValidationError(f"pattern must be a pattern name like ANSI31, got {pattern!r}")
        pattern_name = pattern.strip().upper()
        scale = geometry.validate_positive(scale, "scale")
        angle = geometry.validate_angle_degrees(angle_degrees, "angle_degrees")
        if boundary_points is not None:
            points = geometry.validate_points(boundary_points, "boundary_points")
            if len(points) < 3:
                raise geometry.ValidationError("boundary_points needs at least 3 points")
        else:
            if not isinstance(boundary_handles, list) or not boundary_handles:
                raise geometry.ValidationError("boundary_handles must be a non-empty list")

        def run():
            doc = self._require_doc(write=True)
            name = self._layer(doc, layer)
            if pattern_name != "SOLID":
                import difflib

                from ezdxf.tools import pattern as pattern_tables

                known = pattern_tables.load(measurement=1 if doc.header.get("$MEASUREMENT", 0) == 1 else 0)
                if pattern_name not in known:
                    close = difflib.get_close_matches(pattern_name, list(known), n=5)
                    raise geometry.ValidationError(
                        f"unknown hatch pattern {pattern_name!r}" + (f"; did you mean {close}?" if close else ""))
            boundary_handle = None
            if boundary_points is not None:
                loop = [(p[0], p[1]) for p in points]
                if keep_boundary:
                    boundary = self._msp().add_lwpolyline(loop, close=True, dxfattribs={"layer": name})
                    boundary_handle = boundary.dxf.handle
            else:
                loop = None
                for h in boundary_handles:
                    e = self._entity(h)
                    info = describe(e, full=False)
                    if info["type"] == "LWPOLYLINE" and info["closed"] and not info.get("has_bulges"):
                        loop = [(p[0], p[1]) for p in info["points"]]
                    elif info["type"] == "POLYLINE3D" and info["closed"]:
                        loop = [(p[0], p[1]) for p in info["points"]]
                    elif info["type"] == "CIRCLE":
                        cx, cy, _ = info["center"]
                        r = info["radius"]
                        loop = [(cx + r * math.cos(2 * math.pi * k / 72), cy + r * math.sin(2 * math.pi * k / 72))
                                for k in range(72)]
                    else:
                        raise self._unsupported_reason(
                            "add_hatch", "headless boundaries must be one closed straight-sided polyline or a circle")
                    break
            hatch = self._msp().add_hatch(color=256, dxfattribs={"layer": name})
            if pattern_name == "SOLID":
                hatch.set_solid_fill(color=256)
            else:
                hatch.set_pattern_fill(pattern_name, scale=scale, angle=angle)
            hatch.paths.add_polyline_path(loop, is_closed=True)
            area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(loop, loop[1:] + loop[:1]))) / 2.0
            return self._result(handle=hatch.dxf.handle, layer=name, pattern=hatch.dxf.pattern_name, scale=scale,
                                angle_degrees=angle, area=area, boundary_handle=boundary_handle,
                                boundary_handles=boundary_handles, verified=hatch.dxf.pattern_name == pattern_name,
                                verification="pattern_name_set", message=f"Hatched with {pattern_name}, area {area:g}.")
        return self._run(run)

    # ======= blocks =======

    def list_blocks(self, include_anonymous=False):
        def run():
            doc = self._require_doc(write=False)
            rows = []
            for block in doc.blocks:
                if block.is_any_layout or (block.name.startswith("*") and not include_anonymous):
                    continue
                rows.append({"name": block.name, "entity_count": len(block), "is_xref": bool(block.block.is_xref),
                             "xref_path": None, "attribute_tags": [a.dxf.tag for a in block.query("ATTDEF")]})
            rows.sort(key=lambda r: r["name"].lower())
            return self._result(count=len(rows), blocks=rows)
        return self._run(run)

    def insert_block(self, name, insertion_point, scale=1.0, rotation_degrees=0.0, layer=None, attributes=None):
        if not isinstance(name, str) or not name.strip():
            raise geometry.ValidationError("name must be a non-empty block name")
        p = geometry.validate_point_2d_or_3d(insertion_point, "insertion_point")
        scale = geometry.validate_positive(scale, "scale")
        rotation = geometry.validate_angle_degrees(rotation_degrees, "rotation_degrees")
        if attributes is not None and (not isinstance(attributes, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in attributes.items())):
            raise geometry.ValidationError("attributes must map tag strings to value strings")

        def run():
            doc = self._require_doc(write=True)
            if name.strip() not in doc.blocks:
                raise CadStateError(f"Block {name!r} is not defined in this drawing.", code="E_BLOCK_NOT_FOUND")
            block = doc.blocks.get(name.strip())
            defined = {a.dxf.tag.upper(): a.dxf.tag for a in block.query("ATTDEF")}
            if attributes:
                unknown = sorted(t for t in attributes if t.upper() not in defined)
                if unknown:
                    raise geometry.ValidationError(f"block {name!r} defines no attribute tag(s) {unknown}")
            ref = self._msp().add_blockref(name.strip(), p, dxfattribs={"layer": self._layer(doc, layer),
                                                                        "xscale": scale, "yscale": scale,
                                                                        "zscale": scale, "rotation": rotation})
            if defined:
                ref.add_auto_attribs({defined[k.upper()]: v for k, v in (attributes or {}).items()})
            values = {a.dxf.tag: a.dxf.text for a in ref.attribs}
            return self._result(handle=ref.dxf.handle, block=name.strip(), insertion_point=p, scale=scale,
                                rotation_degrees=rotation, layer=ref.dxf.layer, attributes=values, verified=True,
                                verification="block_reference_and_attributes", message=f"Inserted block {name!r}.")
        return self._run(run)

    def get_block_attributes(self, handle):
        def run():
            self._require_doc(write=False)
            ref = self._entity(handle)
            if ref.dxftype() != "INSERT":
                raise geometry.ValidationError(f"{handle} is not a block reference")
            rows = [{"tag": a.dxf.tag, "value": a.dxf.text, "handle": a.dxf.handle} for a in ref.attribs]
            return self._result(handle=handle, block=ref.dxf.name, attributes=rows)
        return self._run(run)

    def set_block_attributes(self, handle, values):
        if not isinstance(values, dict) or not values or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in values.items()):
            raise geometry.ValidationError("values must be a non-empty map of tag -> text")

        def run():
            self._require_doc(write=True)
            ref = self._entity(handle)
            if ref.dxftype() != "INSERT":
                raise geometry.ValidationError(f"{handle} is not a block reference")
            by_tag = {a.dxf.tag.upper(): a for a in ref.attribs}
            unknown = sorted(t for t in values if t.upper() not in by_tag)
            if unknown:
                raise geometry.ValidationError(f"no attribute tag(s) {unknown} on this block; tags: {sorted(by_tag)}")
            before = {t: a.dxf.text for t, a in by_tag.items()}
            for tag, value in values.items():
                by_tag[tag.upper()].dxf.text = value
            after = {t: a.dxf.text for t, a in by_tag.items()}
            return self._result(handle=handle, before=before, after=after, verified=True,
                                verification="attribute_text_set", mismatched={},
                                message=f"Updated {len(values)} attribute(s) on {handle}.")
        return self._run(run)

    # ======= output =======

    def list_layouts(self):
        def run():
            doc = self._require_doc(write=False)
            rows = [{"name": lo.name, "is_model": lo.name == "Model", "tab_order": lo.dxf_layout.dxf.get("taborder", 0),
                     "plot_device": None, "paper": None, "plot_style": None, "plot_type": None,
                     "current": lo.name == "Model"} for lo in doc.layouts]
            return self._result(count=len(rows), layouts=rows, current_layout="Model")
        return self._run(run)

    def export_dxf(self, path, overwrite=False):
        target = output_path(path, suffixes=(".dxf",), overwrite=overwrite)

        def run():
            doc = self._require_doc(write=False)
            temp = target.with_name(f".{target.stem}.{uuid.uuid4().hex[:8]}.dxf")
            with open(temp, "wt", encoding="utf-8", newline="") as fh:
                doc.write(fh)
            os.replace(temp, target)
            import ezdxf

            reread = ezdxf.readfile(str(target))
            same = len(reread.modelspace()) == len(self._msp())
            return self._result(file=file_evidence(target), document_unchanged=True, verified=same,
                                verification="file_re_read_with_same_entity_count",
                                message=f"Exported a DXF copy to {target}; the open drawing is unchanged.")
        return self._run(run)

    def render_preview(self, path, overwrite=False):
        target = output_path(path, suffixes=(".png", ".pdf", ".svg"), overwrite=overwrite)

        def run():
            self._require_doc(write=False)
            if importlib.util.find_spec("matplotlib") is None:
                raise DependencyMissingError(
                    'headless previews need matplotlib: pip install -e ".[render]"')
            from ezdxf.addons.drawing import matplotlib as ezdxf_mpl

            ezdxf_mpl.qsave(self._msp(), str(target))
            return self._result(file=file_evidence(target), verified=os.path.getsize(target) > 0,
                                verification="file_on_disk", message=f"Rendered model space to {target}.")
        return self._run(run)

    # ======= composite drafting =======

    def draw_wall(self, start_point, end_point, thickness=None, layer="A-WALL"):
        start = geometry.validate_point_2d_or_3d(start_point, "start_point")
        end = geometry.validate_point_2d_or_3d(end_point, "end_point")
        if thickness is not None:
            thickness = geometry.validate_positive(thickness, "thickness")
        layer = geometry.validate_layer_name(layer)
        geometry.wall_outline_points(start, end, 1.0)

        def run():
            doc = self._require_doc(write=True)
            t = thickness if thickness is not None else units.defaults_for(self._insunits() or 1)["exterior_wall"]
            outline = geometry.wall_outline_points(start, end, t)
            standard = ARCHITECTURAL_LAYERS.get(layer)
            if layer not in doc.layers:
                doc.layers.add(layer, color=standard["color_index"] if standard else 7)
            e = self._msp().add_polyline3d(outline, close=True, dxfattribs={"layer": layer})
            return self._result(handle=e.dxf.handle, start_point=start, end_point=end, thickness=t, layer=layer,
                                outline=outline, verified=True, verification="entity_in_modelspace",
                                message=f"Created wall {e.dxf.handle} from {start} to {end}, thickness {t}.")
        return self._run(run)

    def emit_plan(self, build, dry_run=False):
        """build(drawing_insunits) -> Plan; returns (plan, handles|None, identity, code)."""
        from backends.targets import DxfTarget, emit

        def run():
            doc = self._require_doc(write=not dry_run)
            code = self._insunits() or 1
            plan = build(code)
            if dry_run:
                return plan, None, self._identity(), code
            return plan, emit(plan, DxfTarget(doc)), self._identity(), code
        with self._lock:
            result, notices = session.collect(run)
        return result, notices

    def generate_2d_floor_plan(self, width_ft=24.0, length_ft=30.0, units="INCHES", rooms_config=None,
                               dry_run=False):
        from domain.architecture import VALID_UNITS as _VALID_UNITS
        from domain.architecture import build_grid_plan, grid_plan_result

        units_label = units
        if not isinstance(units_label, str) or units_label.upper() not in _VALID_UNITS:
            raise geometry.ValidationError(f"units must be one of {sorted(_VALID_UNITS)}, got {units_label!r}")
        base, build = build_grid_plan(width_ft, length_ft, rooms_config)
        (plan, handles, identity, code), notices = self.emit_plan(build, dry_run=dry_run)
        result = grid_plan_result(plan, handles, width_ft=float(width_ft), length_ft=float(length_ft),
                                  units_label=units_label.upper(), drawing_code=code, identity=identity,
                                  dry_run=dry_run)
        result["backend"] = self.name
        if notices:
            result["notices"] = notices
        return result

    # ======= civil =======

    def _civil_alignment(self, handle, label="alignment"):
        """LINE or polyline as a centreline; anything else refuses."""
        e = self._entity(handle)
        t = e.dxftype()
        if t == "LINE":
            points = [_p3(e.dxf.start), _p3(e.dxf.end)]
            closed = False
        elif t == "LWPOLYLINE":
            raw = [tuple(float(c) for c in p) for p in e.get_points("xyseb")]
            points = [[p[0], p[1], 0.0] for p in raw]
            closed = bool(e.closed)
            bulges = sum(1 for p in raw if p[4])
            if bulges:
                session.add_notice("alignment_arc_bulges_as_chords", handle=e.dxf.handle, bulge_vertices=bulges,
                                   checked=True)
        elif t == "POLYLINE":
            points = [_p3(v.dxf.location) for v in e.vertices]
            closed = bool(e.is_closed)
            bulges = sum(1 for v in e.vertices if v.dxf.get("bulge", 0.0))
            if bulges:
                session.add_notice("alignment_arc_bulges_as_chords", handle=e.dxf.handle, bulge_vertices=bulges,
                                   checked=True)
        else:
            raise CadStateError(
                f"{label} {handle} is a {t} entity; stationing needs a LINE or a polyline "
                "(LWPOLYLINE, POLYLINE or 3D polyline).",
                code="E_UNSUPPORTED_ENTITY",
                details={"handle": handle, "type": t},
            )
        if len(points) < 2:
            raise CadStateError(f"{label} {handle} has fewer than 2 usable vertices.", code="E_UNSUPPORTED_ENTITY",
                                details={"handle": handle, "type": t})
        kind = "POLYLINE3D" if (t == "POLYLINE" and e.is_3d_polyline) else t
        return {"handle": e.dxf.handle, "type": kind, "closed": closed, "points": points,
                "length": civil.alignment_length(points, closed=closed)}

    def _civil_point_samples(self, layer, max_entities):
        wanted = layer.lower() if layer else None
        samples, layers_seen = [], []
        for e in self._iter(max_entities):
            if e.dxftype() != "POINT":
                continue
            entity_layer = str(e.dxf.get("layer", "0"))
            if wanted is not None and entity_layer.lower() != wanted:
                continue
            samples.append(_p3(e.dxf.location))
            if entity_layer not in layers_seen:
                layers_seen.append(entity_layer)
        total = len(self._msp())
        return {"samples": samples, "scanned_entities": min(total, max_entities), "truncated": total > max_entities,
                "layers_seen": layers_seen}

    @staticmethod
    def _civil_input_list(values, label, validate_item, *, limit=MAX_CIVIL_QUERY_POINTS, hint=""):
        if not isinstance(values, (list, tuple)) or not values:
            raise geometry.ValidationError(f"{label} must be a non-empty list{hint}, got {values!r}")
        if len(values) > limit:
            raise geometry.ValidationError(f"{label} has {len(values)} entries; the limit is {limit}")
        return [validate_item(v, f"{label}[{i}]") for i, v in enumerate(values)]

    def civil_alignment_station(self, alignment, points, start_station=0.0):
        wanted = self._civil_input_list(points, "points", geometry.validate_point_2d_or_3d,
                                        hint=" of [x, y] or [x, y, z] points")
        start_station = geometry.validate_number(start_station, "start_station")

        def run():
            self._require_doc(write=False)
            data = self._civil_alignment(alignment)
            rows = []
            for point in wanted:
                result = civil.station_offset(data["points"], point, closed=data["closed"],
                                              start_station=start_station)
                rows.append({"point": list(point), "station": result["station"], "offset": result["offset"],
                             "closest_point": result["closest_point"], "plan_distance": result["plan_distance"],
                             "z_difference": result["z_difference"], "segment_index": result["segment_index"]})
            length = data["length"]
            return self._result(
                alignment={"handle": data["handle"], "type": data["type"], "closed": data["closed"],
                           "vertex_count": len(data["points"]), "length": length, "start_station": start_station,
                           "end_station": start_station + length},
                points=rows,
                message=f"{len(rows)} point(s) queried against a {length:.3f}-unit alignment.")
        return self._run(run)

    def civil_station_point(self, alignment, stations, offset=0.0, start_station=0.0):
        wanted = self._civil_input_list(stations, "stations", geometry.validate_number,
                                        hint=" of station numbers")
        offset = geometry.validate_number(offset, "offset")
        start_station = geometry.validate_number(start_station, "start_station")

        def run():
            self._require_doc(write=False)
            data = self._civil_alignment(alignment)
            rows = []
            for station in wanted:
                result = civil.point_at_station(data["points"], station, offset=offset, closed=data["closed"],
                                                start_station=start_station)
                rows.append({"station": result["station"], "offset": result["offset"], "point": result["point"],
                             "tangent_angle_degrees": result["tangent_angle_degrees"],
                             "segment_index": result["segment_index"], "clamped": result["clamped"]})
            return self._result(
                alignment={"handle": data["handle"], "type": data["type"], "closed": data["closed"],
                           "length": data["length"], "start_station": start_station,
                           "end_station": start_station + data["length"]},
                stations=rows, clamped_count=sum(1 for row in rows if row["clamped"]),
                message=f"{len(rows)} station(s) computed on a {data['length']:.3f}-unit alignment.")
        return self._run(run)

    def civil_ground_profile(self, alignment, interval, layer=None, offset=0.0, method="idw", neighbours=8,
                             start_station=0.0, max_entities=20000):
        interval = geometry.validate_positive(interval, "interval")
        offset = geometry.validate_number(offset, "offset")
        start_station = geometry.validate_number(start_station, "start_station")
        if layer is not None:
            layer = geometry.validate_layer_name(layer)
        max_entities = validate_limit(max_entities, default=20000, maximum=500000, label="max_entities")

        def run():
            self._require_doc(write=False)
            data = self._civil_alignment(alignment)
            series = civil.station_series(start_station, interval, start_station + data["length"],
                                          max_rows=MAX_CIVIL_PROFILE_SAMPLES)
            places = []
            for station in series["stations"]:
                at = civil.point_at_station(data["points"], station, offset=offset, closed=data["closed"],
                                            start_station=start_station)
                places.append((at["station"], at["point"][0], at["point"][1]))
            found = self._civil_point_samples(layer, max_entities)
            rows = civil.sample_profile(places, found["samples"], method=method, neighbours=neighbours)
            elevations = [row["elevation"] for row in rows if row["elevation"] is not None]
            result = self._result(
                alignment={"handle": data["handle"], "type": data["type"], "closed": data["closed"],
                           "length": data["length"], "start_station": start_station,
                           "end_station": start_station + data["length"]},
                interval=interval, offset=offset,
                spot_levels={"count": len(found["samples"]), "layer": layer,
                             "layers_seen": found["layers_seen"] if layer is None else None,
                             "scanned_entities": found["scanned_entities"], "scan_truncated": found["truncated"]},
                stations=rows, rows_truncated=series["truncated"],
                missing_elevations=len(rows) - len(elevations),
                elevation_min=min(elevations) if elevations else None,
                elevation_max=max(elevations) if elevations else None)
            if not found["samples"]:
                result["message"] = ("No POINT entities with a Z were found"
                                     + (f" on layer {layer!r}." if layer else " in ModelSpace.")
                                     + " Every station reports elevation null.")
            else:
                result["message"] = (f"{len(rows)} station(s) sampled from {len(found['samples'])} spot level(s); "
                                     f"{result['missing_elevations']} without a value.")
            return result
        return self._run(run)

    def civil_surface_volumes(self, existing_layer, design_layer, cell_size, method="idw", neighbours=8,
                              max_entities=20000):
        existing_layer = geometry.validate_layer_name(existing_layer, "existing_layer")
        design_layer = geometry.validate_layer_name(design_layer, "design_layer")
        max_entities = validate_limit(max_entities, default=20000, maximum=500000, label="max_entities")

        def run():
            self._require_doc(write=False)
            ground = self._civil_point_samples(existing_layer, max_entities)
            design = self._civil_point_samples(design_layer, max_entities)
            for samples, name in ((ground, existing_layer), (design, design_layer)):
                if not samples["samples"]:
                    raise CadStateError(
                        f"No POINT entities with a Z were found on layer {name!r}.",
                        code="E_ENTITY_NOT_FOUND",
                        details={"layer": name},
                        recommended_action=("add POINT entities with Z to that layer, or pass the layer "
                                            "that holds the spot levels"),
                    )
            result = civil.grid_volumes(ground["samples"], design["samples"], cell_size, method=method,
                                        neighbours=neighbours)
            return self._result(
                existing_layer=existing_layer, design_layer=design_layer, **result,
                spot_levels={"existing": {"count": len(ground["samples"]), "scan_truncated": ground["truncated"]},
                             "design": {"count": len(design["samples"]), "scan_truncated": design["truncated"]}},
                message=(f"Grid method over {result['cells_total']} cell(s) of {result['cell_size']} unit(s): "
                         f"cut {result['cut_volume']:.3f}, fill {result['fill_volume']:.3f} "
                         f"(net {result['net_volume']:.3f}, positive = surplus fill). "
                         "A drafting aid from the spot levels given, not a survey report."))
        return self._run(run)

    def civil_pipe_clearance(self, first, second, first_diameter=None, second_diameter=None):
        def run():
            self._require_doc(write=False)
            first_data = self._civil_alignment(first, label="first pipe")
            second_data = self._civil_alignment(second, label="second pipe")
            result = civil.pipe_clearance(first_data["points"], second_data["points"],
                                          first_diameter=first_diameter, second_diameter=second_diameter)
            return self._result(
                first_pipe={"handle": first_data["handle"], "type": first_data["type"],
                            "vertex_count": len(first_data["points"])},
                second_pipe={"handle": second_data["handle"], "type": second_data["type"],
                             "vertex_count": len(second_data["points"])},
                **result,
                message=(f"Closest approach {result['minimum_distance']:.3f} unit(s) over "
                         f"{len(result['crossings'])} plan crossing(s)."))
        return self._run(run)

    def civil_place_points(self, points, layer="C-POINT", label=True, text_height=None, start_number=1):
        wanted = self._civil_input_list(points, "points", geometry.validate_point_2d_or_3d,
                                        hint=" of [x, y] or [x, y, z] points", limit=MAX_CIVIL_PLACE_POINTS)
        layer = geometry.validate_layer_name(layer)
        if isinstance(start_number, bool) or not isinstance(start_number, int) or start_number < 0:
            raise geometry.ValidationError(f"start_number must be a non-negative integer, got {start_number!r}")
        if text_height is not None:
            text_height = geometry.validate_positive(text_height, "text_height")

        def run():
            doc = self._require_doc(write=True)
            name = self._layer(doc, layer)
            height = text_height if text_height is not None else units.defaults_for(self._insunits() or 1)["text_height"]
            placed = []
            for index, point in enumerate(wanted):
                number = start_number + index
                marker = self._msp().add_point(point, dxfattribs={"layer": name})
                row = {"number": number, "point": list(point), "handle": marker.dxf.handle}
                if label:
                    text = str(number) if point[2] == 0 else f"{number} Z={point[2]:g}"
                    anchor = (point[0] + height * 0.5, point[1] + height * 0.5, point[2])
                    tag = self._msp().add_text(text, height=height, dxfattribs={"layer": name})
                    tag.set_placement(anchor)
                    row["label_handle"] = tag.dxf.handle
                placed.append(row)
            for row in placed:
                if self._entity(row["handle"]).dxftype() != "POINT":
                    raise VerificationError(f"Entity {row['handle']} is not a POINT after creation.")
                if label and self._entity(row["label_handle"]).dxftype() != "TEXT":
                    raise VerificationError(f"Entity {row['label_handle']} is not a TEXT label after creation.")
            return self._result(
                layer=name, points=placed, count=len(placed), labelled=bool(label), text_height=height,
                verified=True, verification="entities_read_back_from_entitydb",
                message=(f"Placed {len(placed)} point marker(s) on layer {name!r}"
                         + (f" with number/level labels at height {height}." if label else ".")))
        return self._run(run)
