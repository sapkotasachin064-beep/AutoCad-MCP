"""Stable identity for the active drawing, used to key database records.

AutoCAD's COM Document object has no GUID. The best stable key available is
the saved file path -- but doc.Path is NOT a reliable "has this been saved"
signal: verified against a live AutoCAD 2024, a brand-new unsaved document's
Path is the process's current working directory (non-empty), not "". The
reliable signal is doc.FullName, which is "" until the document is saved
at least once and "" again is never reused by AutoCAD for a real path. An
unsaved drawing has no identity that survives past this AutoCAD session,
which every caller must treat as a real limitation, not an edge case to
paper over.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DrawingIdentity:
    identity: str
    name: str
    path: str | None
    saved: bool


def get_drawing_identity(doc) -> DrawingIdentity:
    name = doc.Name
    full_name = (doc.FullName or "").strip()
    if full_name:
        identity = f"path:{full_name.lower()}"
        return DrawingIdentity(identity=identity, name=name, path=full_name, saved=True)
    identity = f"unsaved:{name.lower()}"
    return DrawingIdentity(identity=identity, name=name, path=None, saved=False)
