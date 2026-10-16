"""Evidence for outputs, and helpers that keep responses bounded.

A written file is reported by what is on disk -- size and SHA-256 read back
after the write -- never by the writer's return value alone.
"""

import hashlib
import os
from datetime import datetime, timezone


def file_evidence(path) -> dict:
    path = os.fspath(path)
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    stat = os.stat(path)
    return {
        "path": path,
        "size_bytes": stat.st_size,
        "sha256": digest.hexdigest(),
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
    }


def validate_limit(limit, *, default: int, maximum: int, label: str = "limit") -> int:
    from utils.geometry import ValidationError

    if limit is None:
        return default
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValidationError(f"{label} must be an integer, got {limit!r}")
    if not 1 <= limit <= maximum:
        raise ValidationError(f"{label} must be between 1 and {maximum}, got {limit}")
    return limit


def validate_offset(offset, label: str = "offset") -> int:
    from utils.geometry import ValidationError

    if offset is None:
        return 0
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValidationError(f"{label} must be a non-negative integer, got {offset!r}")
    return offset


def page(items: list, *, offset: int, limit: int) -> dict:
    """Slice a list and describe the slice, so a truncated answer says so."""
    total = len(items)
    window = items[offset: offset + limit]
    return {
        "items": window,
        "total": total,
        "offset": offset,
        "returned": len(window),
        "truncated": offset + len(window) < total,
        "next_offset": offset + len(window) if offset + len(window) < total else None,
    }
