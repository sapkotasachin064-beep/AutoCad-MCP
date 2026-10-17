"""Reusable typed schemas for MCP tool arguments.

The MCP SDK (2.x) generates each tool's JSON input schema from the evaluated
annotations on its function signature, so the description attached here is
exactly what an agent sees when it reads the tool definition: keep it factual
and unit-bearing. Annotations carry types only; argument semantics (valid
ranges, enum membership) stay validated in the tools, whose error envelopes
carry `recommended_action`.
"""

from typing import Annotated

from pydantic import Field

# Coordinates: the drawing's own units, as reported by autocad_get_status /
# autocad_drawing_summary (never hard-coded to mm or inches).
Point = Annotated[list[float], Field(
    description="[x, y] or [x, y, z] in the drawing's own units; z defaults to 0."
)]
Points = Annotated[list[list[float]], Field(
    description="Ordered vertices in the drawing's own units; each is [x, y] or [x, y, z]."
)]

# Unit for the lengths a drawing macro takes (sizes, spacings, offsets, text height).
# Coordinates (start points, origins, positions) stay in the drawing's own units.
MacroUnit = Annotated[str | None, Field(
    description="Unit of every length argument that is not a coordinate (sizes, spacings, offsets, text "
                "height): 'mm', 'cm', 'm', 'in' or 'ft'. null = the drawing's own units. Coordinates "
                "(start points, origins, positions) are always in drawing units."
)]

# Entity handles: opaque hex strings AutoCAD assigns, e.g. '2A7F'.
Handle = Annotated[str, Field(
    description="AutoCAD entity handle as reported, a hex string e.g. '2A7F'; "
                "from autocad_list_entities or an insert tool's result."
)]
Handles = Annotated[list[str], Field(
    description="One or more entity handles (hex strings); from autocad_list_entities "
                "or insert tool results."
)]

# Layers: names follow the AIA/ISO 13567-style standard (A-WALL, A-DOOR, ...).
Layer = Annotated[str | None, Field(
    description="Layer name such as 'A-WALL'; created if it does not exist. "
                "null leaves the entity on its current layer."
)]
LayerName = Annotated[str, Field(
    description="Layer name such as 'A-WALL'; created if it does not exist."
)]
