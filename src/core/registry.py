"""Machine-readable registry of the public MCP tools.

Each tool is registered with a ToolSpec: its toolset, its side-effect kind
(which becomes the MCP ToolAnnotations hints), and the backend operation it
calls. The capability map is derived from code: a backend supports an
operation exactly when its class overrides that method of backends.base.Backend.

Toolsets let a client with a tight tool budget advertise less:
AUTOCAD_MCP_TOOLSETS=all (default) or a comma list such as
"core,drawing,analysis". `core` is always enabled.
"""

import os
from dataclasses import asdict, dataclass, field

from core.errors import ConfigError

TOOLSETS = {
    "core": "status, launch, capabilities, document lifecycle, pinning, units",
    "drawing": "2D primitives: lines, polylines, rectangles, circles, arcs, text, MTEXT",
    "layers": "layer creation, listing and properties",
    "editing": "move, rotate, copy, scale, mirror, offset, array, delete, properties, highlight",
    "query": "drawing summary, entity listing and detail, scan to SQLite, read-only SQL, text search",
    "annotation": "dimensions and hatches",
    "blocks": "block definitions, insertion and attributes",
    "architecture": "walls, floor plans, stairs, structural grids, sheets and title blocks",
    "analysis": "drawing checks, quantity takeoff, DXF comparison",
    "output": "DXF export, PDF plotting, layouts, previews, file evidence",
}

# kind -> (readOnlyHint, destructiveHint, idempotentHint)
KINDS = {
    "read": (True, False, True),          # never changes a drawing or a file
    "session": (False, False, True),      # changes server/session state only (pin, unpin)
    "write": (False, False, False),       # adds to or changes the drawing, never removes
    "destructive": (False, True, False),  # can remove or overwrite work (delete, close, overwrite)
    "external": (False, False, False),    # writes files or starts processes outside the drawing
}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    toolset: str
    kind: str
    title: str
    operation: str | None = None  # Backend method it calls; None = backend-independent
    notes: str = ""
    extra: dict = field(default_factory=dict)

    def annotations(self) -> dict:
        read_only, destructive, idempotent = KINDS[self.kind]
        return {
            "title": self.title,
            "read_only_hint": read_only,
            "destructive_hint": destructive,
            "idempotent_hint": idempotent,
            "open_world_hint": False,
        }


_SPECS: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    if spec.toolset not in TOOLSETS:
        raise ValueError(f"unknown toolset {spec.toolset!r} for {spec.name}")
    if spec.kind not in KINDS:
        raise ValueError(f"unknown kind {spec.kind!r} for {spec.name}")
    if spec.name in _SPECS:
        raise ValueError(f"tool {spec.name} registered twice")
    _SPECS[spec.name] = spec
    return spec


def specs() -> dict[str, ToolSpec]:
    return dict(_SPECS)


def enabled_toolsets() -> set[str]:
    raw = os.environ.get("AUTOCAD_MCP_TOOLSETS", "all").strip().lower() or "all"
    if raw == "all":
        return set(TOOLSETS)
    chosen = {part.strip() for part in raw.split(",") if part.strip()}
    unknown = chosen - set(TOOLSETS)
    if unknown:
        raise ConfigError(
            f"AUTOCAD_MCP_TOOLSETS names unknown toolsets {sorted(unknown)}; "
            f"valid: all, {', '.join(TOOLSETS)}"
        )
    return chosen | {"core"}


def supported_operations(backend_cls) -> set[str]:
    from backends.base import Backend

    supported = set()
    for name in Backend.OPERATIONS:
        if getattr(backend_cls, name) is not getattr(Backend, name):
            supported.add(name)
    return supported


def capability_map() -> dict:
    """Which tools each backend can serve, computed from the code."""
    from backends.dxf import DxfBackend

    per_backend = {"dxf": supported_operations(DxfBackend)}
    try:
        from backends.com import ComBackend
    except ImportError:  # no pywin32 (non-Windows): the live backend cannot exist here
        per_backend["com"] = set()
    else:
        per_backend["com"] = supported_operations(ComBackend)
    per_backend = {"com": per_backend["com"], "dxf": per_backend["dxf"]}
    tools = {}
    for name, spec in sorted(_SPECS.items()):
        if spec.operation is None:
            available = ["com", "dxf"]  # backend-independent (pure logic, files, session)
        else:
            available = [b for b, ops in per_backend.items() if spec.operation in ops]
        tools[name] = {
            "toolset": spec.toolset,
            "kind": spec.kind,
            "backends": available,
            "annotations": spec.annotations(),
            **({"notes": spec.notes} if spec.notes else {}),
        }
    return {"tools": tools, "operations": {b: sorted(ops) for b, ops in per_backend.items()}}


def describe_spec(spec: ToolSpec) -> dict:
    return asdict(spec)
