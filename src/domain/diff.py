"""Compare two entity snapshots (pure).

Matching, in order: by handle (revisions of the same file keep handles), then
by geometry signature for entities whose handles differ (e.g. after
copy/paste or a DWG -> DXF round trip). An entity matched by handle whose
type, layer or geometry differs is reported as changed, with the fields that
changed. Read-only: nothing is drawn or modified.
"""

from domain.qc import signature

COMPARED_FIELDS = ("type", "layer", "points", "closed", "center", "radius", "start_angle_degrees",
                   "end_angle_degrees", "text", "insertion_point", "height", "block", "pattern")


def _norm(value, ndigits=6):
    if isinstance(value, float):
        return round(value, ndigits)
    if isinstance(value, (list, tuple)):
        return [_norm(v, ndigits) for v in value]
    return value


def compare(old: list[dict], new: list[dict], *, max_items: int = 200) -> dict:
    old_by_handle = {e["handle"]: e for e in old if e.get("handle")}
    new_by_handle = {e["handle"]: e for e in new if e.get("handle")}
    changed, unchanged = [], 0
    for handle in sorted(old_by_handle.keys() & new_by_handle.keys()):
        a, b = old_by_handle[handle], new_by_handle[handle]
        fields = [f for f in COMPARED_FIELDS if _norm(a.get(f)) != _norm(b.get(f))]
        if fields:
            changed.append({"handle": handle, "type": b.get("type"), "layer": b.get("layer"), "fields": fields,
                            "before": {f: a.get(f) for f in fields}, "after": {f: b.get(f) for f in fields}})
        else:
            unchanged += 1
    removed = [old_by_handle[h] for h in sorted(old_by_handle.keys() - new_by_handle.keys())]
    added = [new_by_handle[h] for h in sorted(new_by_handle.keys() - old_by_handle.keys())]

    # Re-pair removed/added entities that are geometrically identical (new handle, same thing).
    added_by_sig = {}
    for e in added:
        added_by_sig.setdefault(signature(e), []).append(e)
    moved_handles, still_removed = [], []
    for e in removed:
        sig = signature(e)
        if sig is not None and added_by_sig.get(sig):
            twin = added_by_sig[sig].pop()
            moved_handles.append({"old_handle": e["handle"], "new_handle": twin["handle"], "type": e.get("type"),
                                  "layer": e.get("layer")})
        else:
            still_removed.append(e)
    rehandled = {m["new_handle"] for m in moved_handles}
    still_added = [e for e in added if e["handle"] not in rehandled]

    def brief(e):
        return {k: e.get(k) for k in ("handle", "type", "layer", "text", "block") if e.get(k) is not None}

    return {
        "summary": {"unchanged": unchanged, "changed": len(changed), "added": len(still_added),
                    "removed": len(still_removed), "same_geometry_new_handle": len(moved_handles),
                    "old_count": len(old), "new_count": len(new)},
        "changed": changed[:max_items],
        "added": [brief(e) for e in still_added[:max_items]],
        "removed": [brief(e) for e in still_removed[:max_items]],
        "same_geometry_new_handle": moved_handles[:max_items],
        "truncated": any(len(x) > max_items for x in (changed, still_added, still_removed, moved_handles)),
        "identical": not changed and not still_added and not still_removed,
    }
