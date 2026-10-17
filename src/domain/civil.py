"""Civil and survey maths over plain coordinates: centreline (alignment)
stationing, ground-level sampling, earthwork volumes and pipe clearance.

Pure: no COM, no ezdxf, no files -- the live and the headless backend share
one implementation. The backends read ordinary AutoCAD entities (a LINE or
polyline centreline, POINT entities as spot levels) and hand their points to
these functions. No Civil 3D object is involved and no result is a design
check: this is drafting arithmetic on the data the user points at.

Conventions, kept everywhere in this module:

* Stations run along the centreline from its first vertex, in drawing units,
  measured in plan (X/Y); z never changes a station.
* Offset is perpendicular to the direction of increasing station and is
  positive on the right of that direction in a Y-up drawing (standard
  AutoCAD coordinates), negative on the left.
* Angles are degrees in the AutoCAD convention: 0 points along +X and
  angles grow counterclockwise.
"""

import math

from utils import geometry

METHODS = ("idw", "nearest")
MAX_SAMPLE_NEIGHBOURS = 64


def _point_list(points, label: str, minimum: int = 2) -> list[tuple]:
    if not isinstance(points, (list, tuple)) or len(points) < minimum:
        raise geometry.ValidationError(f"{label} must be a list of at least {minimum} points, got {points!r}")
    return [geometry.validate_point_2d_or_3d(p, f"{label}[{i}]") for i, p in enumerate(points)]


def _segments(points, closed: bool):
    segments = list(zip(points, points[1:]))
    if closed and len(points) >= 3:
        segments.append((points[-1], points[0]))
    return segments


def _bounds(samples) -> dict:
    return {"min": [min(p[0] for p in samples), min(p[1] for p in samples)],
            "max": [max(p[0] for p in samples), max(p[1] for p in samples)]}


def _convex_hull(samples) -> list[tuple]:
    """Plan-view convex hull (monotone chain), counterclockwise. Fewer than
    three points, or collinear points, give a hull that covers no area."""
    pts = sorted({(float(p[0]), float(p[1])) for p in samples})
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for point in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _inside_hull(hull, x: float, y: float) -> bool:
    if len(hull) < 3:
        return False
    for i in range(len(hull)):
        ax, ay = hull[i]
        bx, by = hull[(i + 1) % len(hull)]
        if (bx - ax) * (y - ay) - (by - ay) * (x - ax) < -1e-9:
            return False
    return True


def _method(method: str) -> str:
    if method not in METHODS:
        raise geometry.ValidationError(f"method must be one of {', '.join(METHODS)}, got {method!r}")
    return method


def _neighbours(neighbours) -> int:
    if isinstance(neighbours, bool) or not isinstance(neighbours, int):
        raise geometry.ValidationError(f"neighbours must be an integer, got {neighbours!r}")
    if not 1 <= neighbours <= MAX_SAMPLE_NEIGHBOURS:
        raise geometry.ValidationError(f"neighbours must be between 1 and {MAX_SAMPLE_NEIGHBOURS}, got {neighbours}")
    return neighbours


def alignment_length(points, *, closed: bool = False) -> float:
    pts = _point_list(points, "points", minimum=2)
    return sum(math.dist(a[:2], b[:2]) for a, b in _segments(pts, closed))


def station_offset(points, point, *, closed: bool = False, start_station: float = 0.0) -> dict:
    """Station and offset of `point` on the centreline `points`.

    The closest point on the centreline (in plan) defines the station; the
    offset is the signed plan distance to it. `closest_point` carries the
    centreline's own z at that station, and `z_difference` is
    point.z - closest_point.z.
    """
    pts = _point_list(points, "points", minimum=2)
    target = geometry.validate_point_2d_or_3d(point, "point")
    start_station = geometry.validate_number(start_station, "start_station")

    best = None
    station_at_start = start_station
    for index, (a, b) in enumerate(_segments(pts, closed)):
        seg_len = math.dist(a[:2], b[:2])
        if seg_len <= 0:
            continue
        dx, dy = (b[0] - a[0]) / seg_len, (b[1] - a[1]) / seg_len
        along = (target[0] - a[0]) * dx + (target[1] - a[1]) * dy
        along = min(seg_len, max(0.0, along))
        cx, cy = a[0] + dx * along, a[1] + dy * along
        distance = math.hypot(target[0] - cx, target[1] - cy)
        if best is None or distance < best["plan_distance"] - 1e-12:
            cross = dx * (target[1] - cy) - dy * (target[0] - cx)
            offset = -distance if cross > 0 else distance
            z = a[2] + (b[2] - a[2]) * (along / seg_len)
            best = {
                "station": station_at_start + along,
                "offset": offset,
                "segment_index": index,
                "closest_point": [cx, cy, z],
                "plan_distance": distance,
                "z_difference": target[2] - z,
            }
        station_at_start += seg_len
    return best


def point_at_station(points, station, *, offset: float = 0.0, closed: bool = False,
                     start_station: float = 0.0) -> dict:
    """The point at `station` (and perpendicular `offset`) on the centreline.

    A station before the start or past the end is clamped to the centreline
    and reported with `clamped: true`; nothing is extrapolated.
    """
    pts = _point_list(points, "points", minimum=2)
    station = geometry.validate_number(station, "station")
    offset_value = geometry.validate_number(offset, "offset")
    start_station = geometry.validate_number(start_station, "start_station")
    segments = _segments(pts, closed)

    total = sum(math.dist(a[:2], b[:2]) for a, b in segments)
    wanted, clamped = station - start_station, False
    if wanted < 0.0:
        wanted, clamped = 0.0, True
    elif wanted > total:
        wanted, clamped = total, True

    travelled = 0.0
    for index, (a, b) in enumerate(segments):
        seg_len = math.dist(a[:2], b[:2])
        if seg_len <= 0:
            continue
        if wanted <= travelled + seg_len or index == len(segments) - 1:
            along = min(seg_len, max(0.0, wanted - travelled))
            t = along / seg_len
            dx, dy = (b[0] - a[0]) / seg_len, (b[1] - a[1]) / seg_len
            # right-hand normal of the direction of increasing station
            nx, ny = dy, -dx
            return {
                "point": [a[0] + dx * along + nx * offset_value,
                          a[1] + dy * along + ny * offset_value,
                          a[2] + (b[2] - a[2]) * t],
                "tangent_angle_degrees": math.degrees(math.atan2(dy, dx)) % 360.0,
                "segment_index": index,
                "station": start_station + travelled + along,
                "offset": offset_value,
                "clamped": clamped,
            }
        travelled += seg_len
    raise geometry.ValidationError("the centreline has no segment of non-zero length")


def station_series(start_station: float, interval: float, end_station: float, *, max_rows: int = 500) -> dict:
    """Stations from start_station to end_station at `interval`, by default
    the end station included as the last row when the step would overshoot.
    `truncated` says the max_rows cap was hit first."""
    start_station = geometry.validate_number(start_station, "start_station")
    interval = geometry.validate_positive(interval, "interval")
    end_station = geometry.validate_number(end_station, "end_station")
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        raise geometry.ValidationError(f"max_rows must be a positive integer, got {max_rows!r}")
    stations = []
    station = start_station
    while station <= end_station + 1e-9 and len(stations) < max_rows:
        stations.append(station)
        station += interval
    truncated = station <= end_station + 1e-9
    if not truncated and stations and end_station - stations[-1] > 1e-9:
        stations.append(end_station)
    return {"stations": stations, "truncated": truncated}


def sample_elevation(samples, x: float, y: float, *, method: str = "idw", neighbours: int = 8,
                     power: float = 2.0) -> float | None:
    """Elevation at (x, y) from spot levels `samples` ([[x, y, z], ...]),
    or None when there are no samples. `idw` is inverse-distance weighting
    over the `neighbours` closest samples; `nearest` takes the closest one.
    An exact hit on a sample returns that sample's z.

    IDW extrapolates beyond the sample coverage, so callers should report
    the sample extent (the tools do) instead of treating edge values as
    surveyed ground.
    """
    method = _method(method)
    neighbours = _neighbours(neighbours)
    power = geometry.validate_positive(power, "power")
    x = geometry.validate_number(x, "x")
    y = geometry.validate_number(y, "y")
    if not samples:
        return None

    distances = []
    for i, sample in enumerate(samples):
        sx, sy = float(sample[0]), float(sample[1])
        distances.append((math.hypot(x - sx, y - sy), float(sample[2])))
    distances.sort(key=lambda item: item[0])
    if distances[0][0] <= 1e-9:
        return distances[0][1]
    if method == "nearest":
        return distances[0][1]
    weights = [(1.0 / distance) ** power for distance, _ in distances[:neighbours]]
    total = sum(weights)
    return sum(weight * z for weight, (_, z) in zip(weights, distances[:neighbours])) / total


def sample_profile(places, samples, *, method: str = "idw", neighbours: int = 8,
                   power: float = 2.0) -> list[dict]:
    """One row per place to sample: places are (station, x, y) tuples, the
    row is {"station", "elevation", "point"} (elevation None when there are
    no samples to read from)."""
    rows = []
    for station, x, y in places:
        station = geometry.validate_number(station, "station")
        x = geometry.validate_number(x, "x")
        y = geometry.validate_number(y, "y")
        rows.append({"station": station, "point": [x, y],
                     "elevation": sample_elevation(samples, x, y, method=method, neighbours=neighbours,
                                                   power=power)})
    return rows


def grid_volumes(existing, design, cell_size, *, method: str = "idw", neighbours: int = 8, power: float = 2.0,
                 max_nodes: int = 250000) -> dict:
    """Cut and fill between two spot-level surfaces by the grid method.

    A square grid of `cell_size` (drawing units) is laid over the overlap of
    the two surfaces' plan extents. Each surface is sampled at every grid
    node from its own spot levels (see `sample_elevation`); nodes outside a
    surface's sample hull are extrapolated and counted in
    `extrapolated_nodes`, so the caller can judge how much of the volume
    rests on extrapolation. A cell contributes
    `cell_size**2 * mean(design_z - existing_z)` over its four corners,
    counted as fill when positive and cut when negative. Positive net volume
    is surplus fill; negative net volume is surplus cut.
    """
    cell = geometry.validate_positive(cell_size, "cell_size")
    method = _method(method)
    neighbours = _neighbours(neighbours)
    power = geometry.validate_positive(power, "power")
    if isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or max_nodes < 1:
        raise geometry.ValidationError(f"max_nodes must be a positive integer, got {max_nodes!r}")
    ground = _point_list(existing, "existing", minimum=1)
    proposed = _point_list(design, "design", minimum=1)

    x0 = max(min(p[0] for p in ground), min(p[0] for p in proposed))
    x1 = min(max(p[0] for p in ground), max(p[0] for p in proposed))
    y0 = max(min(p[1] for p in ground), min(p[1] for p in proposed))
    y1 = min(max(p[1] for p in ground), max(p[1] for p in proposed))
    if x1 <= x0 or y1 <= y0:
        raise geometry.ValidationError("the two surfaces do not overlap in plan, so there is no common grid")
    columns = int(math.floor((x1 - x0) / cell)) + 1
    rows = int(math.floor((y1 - y0) / cell)) + 1
    if columns * rows > max_nodes:
        raise geometry.ValidationError(
            f"cell_size {cell} would need {columns * rows} grid nodes (limit {max_nodes}); "
            "use a larger cell_size"
        )

    def surface_z(samples, x, y):
        return sample_elevation(samples, x, y, method=method, neighbours=neighbours, power=power)

    ground_bounds = _bounds(ground)
    design_bounds = _bounds(proposed)
    ground_hull = _convex_hull(ground)
    design_hull = _convex_hull(proposed)

    node = [[(surface_z(ground, x0 + i * cell, y0 + j * cell),
              surface_z(proposed, x0 + i * cell, y0 + j * cell)) for i in range(columns)] for j in range(rows)]

    extrapolated = {"existing": 0, "design": 0}
    cut = fill = 0.0
    cells_cut = cells_fill = cells_balanced = 0
    dz_values = []
    for j in range(rows):
        for i in range(columns):
            x, y = x0 + i * cell, y0 + j * cell
            if not _inside_hull(ground_hull, x, y):
                extrapolated["existing"] += 1
            if not _inside_hull(design_hull, x, y):
                extrapolated["design"] += 1
    for j in range(rows - 1):
        for i in range(columns - 1):
            corners = (node[j][i], node[j][i + 1], node[j + 1][i], node[j + 1][i + 1])
            mean_dz = sum(design_z - existing_z for existing_z, design_z in corners) / 4.0
            dz_values.append(mean_dz)
            volume = cell * cell * mean_dz
            if abs(volume) <= 1e-9:
                cells_balanced += 1
            elif volume > 0:
                fill += volume
                cells_fill += 1
            else:
                cut += -volume
                cells_cut += 1

    return {
        "cut_volume": cut,
        "fill_volume": fill,
        "net_volume": fill - cut,
        "cell_size": cell,
        "cells_total": (columns - 1) * (rows - 1),
        "cells_cut": cells_cut,
        "cells_fill": cells_fill,
        "cells_balanced": cells_balanced,
        "dz_min": min(dz_values) if dz_values else None,
        "dz_max": max(dz_values) if dz_values else None,
        "grid": {"origin": [x0, y0], "columns": columns, "rows": rows,
                 "origin_max": [x0 + (columns - 1) * cell, y0 + (rows - 1) * cell]},
        "extents": {"existing": ground_bounds, "design": design_bounds},
        "extrapolated_nodes": extrapolated,
    }


def segment_segment_distance(a1, a2, b1, b2) -> dict:
    """Closest 3D approach between segments a1-a2 and b1-b2 (parallel,
    degenerate and skew cases included)."""
    a1 = geometry.validate_point_2d_or_3d(a1, "a1")
    a2 = geometry.validate_point_2d_or_3d(a2, "a2")
    b1 = geometry.validate_point_2d_or_3d(b1, "b1")
    b2 = geometry.validate_point_2d_or_3d(b2, "b2")

    d1 = [a2[i] - a1[i] for i in range(3)]
    d2 = [b2[i] - b1[i] for i in range(3)]
    r = [a1[i] - b1[i] for i in range(3)]
    a = sum(c * c for c in d1)
    e = sum(c * c for c in d2)
    f = sum(d2[i] * r[i] for i in range(3))

    if a <= 1e-18 and e <= 1e-18:
        s = t = 0.0
    elif a <= 1e-18:
        s = 0.0
        t = min(1.0, max(0.0, f / e))
    else:
        c = sum(d1[i] * r[i] for i in range(3))
        if e <= 1e-18:
            t = 0.0
            s = min(1.0, max(0.0, -c / a))
        else:
            b = sum(d1[i] * d2[i] for i in range(3))
            denominator = a * e - b * b
            if denominator > 1e-12:
                s = min(1.0, max(0.0, (b * f - c * e) / denominator))
            else:
                s = 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t = 0.0
                s = min(1.0, max(0.0, -c / a))
            elif t > 1.0:
                t = 1.0
                s = min(1.0, max(0.0, (b - c) / a))
    point_a = [a1[i] + d1[i] * s for i in range(3)]
    point_b = [b1[i] + d2[i] * t for i in range(3)]
    return {
        "distance": math.dist(point_a, point_b),
        "point_on_first": point_a,
        "point_on_second": point_b,
    }


def _plan_crossing(a1, a2, b1, b2):
    """2D intersection of segments a and b when they properly cross in plan.
    Returns (x, y) or None; parallel and collinear pairs return None (the
    3D distance still covers them)."""
    rx, ry = a2[0] - a1[0], a2[1] - a1[1]
    sx, sy = b2[0] - b1[0], b2[1] - b1[1]
    denominator = rx * sy - ry * sx
    if abs(denominator) <= 1e-12:
        return None
    qx, qy = b1[0] - a1[0], b1[1] - a1[1]
    t = (qx * sy - qy * sx) / denominator
    u = (qx * ry - qy * rx) / denominator
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return a1[0] + t * rx, a1[1] + t * ry, t, u
    return None


def pipe_clearance(points_a, points_b, *, first_diameter: float | None = None,
                   second_diameter: float | None = None, max_crossings: int = 50) -> dict:
    """Minimum 3D distance between two pipe runs (polylines of axis points),
    plus every place the two cross in plan with the vertical gap there.

    With both diameters given, `surface_clearance` subtracts the two radii
    from the closest axis distance; both or neither must be given.
    """
    a = _point_list(points_a, "first_pipe", minimum=2)
    b = _point_list(points_b, "second_pipe", minimum=2)
    if (first_diameter is None) != (second_diameter is None):
        raise geometry.ValidationError("give both diameters or neither, so the surface clearance is defined")
    clearance = None
    if first_diameter is not None:
        radii = geometry.validate_positive(first_diameter, "first_diameter") / 2.0 + \
            geometry.validate_positive(second_diameter, "second_diameter") / 2.0
        clearance = -radii  # completed below once the distance is known

    closest = None
    crossings = []
    crossings_truncated = False
    for i, (a1, a2) in enumerate(_segments(a, False)):
        for j, (b1, b2) in enumerate(_segments(b, False)):
            approach = segment_segment_distance(a1, a2, b1, b2)
            if closest is None or approach["distance"] < closest["distance"] - 1e-12:
                closest = {**approach, "segment_on_first": i, "segment_on_second": j}
            crossing = _plan_crossing(a1, a2, b1, b2)
            if crossing is not None:
                if len(crossings) >= max_crossings:
                    crossings_truncated = True
                    continue
                x, y, t, u = crossing
                a_z = a1[2] + (a2[2] - a1[2]) * t
                b_z = b1[2] + (b2[2] - b1[2]) * u
                crossings.append({"point": [x, y], "first_z": a_z, "second_z": b_z, "vertical_gap": b_z - a_z,
                                  "segment_on_first": i, "segment_on_second": j})
    if clearance is not None:
        clearance += closest["distance"]
    return {
        "minimum_distance": closest["distance"],
        "closest": {"on_first_pipe": closest["point_on_first"], "on_second_pipe": closest["point_on_second"],
                    "segment_on_first": closest["segment_on_first"], "segment_on_second": closest["segment_on_second"]},
        "surface_clearance": clearance,
        "crossings": crossings,
        "crossings_truncated": crossings_truncated,
    }
