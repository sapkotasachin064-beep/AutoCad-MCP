"""Structural grid planner (pure; see domain/plan.py).

Grid lines are given as bay spacings: x_spacings run left to right and get
numbers (1, 2, 3, ...), y_spacings run bottom to top and get letters (A, B,
C, ...; I and O are skipped by default because they read as 1 and 0 -- a
common drafting convention, switchable). Each line ends in a labelled
bubble; optional column marks sit at every intersection; a chain of bay
dimensions and an overall dimension run along the bottom and left.

This is drafting of a grid the engineer has chosen, not structural design:
no spans, loads or member sizes are checked.
"""

import string

from domain import units
from domain.plan import Plan, Primitive, rect_points
from utils import geometry

LAYERS = {"S-GRID": (8, "CENTER"), "S-GRID-IDEN": (2, None), "S-COLS": (4, None), "S-ANNO-DIMS": (6, None)}


def _spacings(values, label):
    if not isinstance(values, list) or not values:
        raise geometry.ValidationError(f"{label} must be a non-empty list of bay widths")
    if len(values) > 100:
        raise geometry.ValidationError(f"{label} has more than 100 bays")
    return [geometry.validate_positive(v, f"{label}[{i}]") for i, v in enumerate(values)]


def letters(count: int, skip=("I", "O")) -> list[str]:
    alphabet = [c for c in string.ascii_uppercase if c not in set(skip or ())]
    out = []
    n = 0
    while len(out) < count:
        label, k = "", n
        while True:
            label = alphabet[k % len(alphabet)] + label
            k = k // len(alphabet) - 1
            if k < 0:
                break
        out.append(label)
        n += 1
    return out


def plan_grid(x_spacings, y_spacings, unit_code: int, drawing_code: int, *, origin=(0.0, 0.0),
              extension=None, bubble_diameter=None, text_height=None, column_size=None,
              skip_letters=True, dimensions=True) -> Plan:
    xs_in = _spacings(x_spacings, "x_spacings")
    ys_in = _spacings(y_spacings, "y_spacings")
    f = units.convert(1.0, unit_code, drawing_code)
    ox = geometry.validate_number(origin[0], "origin.x")
    oy = geometry.validate_number(origin[1], "origin.y")
    # paper-based defaults: 10 mm bubbles / 3.5 mm text at 1:100, as drawing units
    mm = units.convert(1.0, units.unit_code("mm"), drawing_code)
    ext = (geometry.validate_positive(extension, "extension") * f) if extension is not None else 1500 * mm
    bubble = (geometry.validate_positive(bubble_diameter, "bubble_diameter") * f) if bubble_diameter is not None else 1000 * mm
    th = (geometry.validate_positive(text_height, "text_height") * f) if text_height is not None else 350 * mm
    col = None
    if column_size is not None:
        if not isinstance(column_size, list) or len(column_size) != 2:
            raise geometry.ValidationError("column_size must be [width, depth]")
        col = (geometry.validate_positive(column_size[0], "column_size[0]") * f,
               geometry.validate_positive(column_size[1], "column_size[1]") * f)

    xs = [ox]
    for s in xs_in:
        xs.append(xs[-1] + s * f)
    ys = [oy]
    for s in ys_in:
        ys.append(ys[-1] + s * f)
    x0, x1, y0, y1 = xs[0], xs[-1], ys[0], ys[-1]
    r = bubble / 2.0

    plan = Plan()
    for name, (color, linetype) in LAYERS.items():
        plan.layer(name, color, linetype)

    numbers = [str(i + 1) for i in range(len(xs))]
    row_labels = letters(len(ys), skip=("I", "O") if skip_letters else ())
    for i, x in enumerate(xs):
        top = y1 + ext
        plan.add(Primitive("line", "S-GRID", f"grid:x:{numbers[i]}", points=((x, y0 - ext, 0.0), (x, top, 0.0))))
        center = (x, top + r, 0.0)
        plan.add(Primitive("circle", "S-GRID-IDEN", f"bubble:x:{numbers[i]}", center=center, radius=r))
        plan.add(Primitive("mtext", "S-GRID-IDEN", f"label:x:{numbers[i]}", text=numbers[i], location=center,
                           height=th, width=0.0, attach="middle_center"))
    for j, y in enumerate(ys):
        left = x0 - ext
        plan.add(Primitive("line", "S-GRID", f"grid:y:{row_labels[j]}", points=((left, y, 0.0), (x1 + ext, y, 0.0))))
        center = (left - r, y, 0.0)
        plan.add(Primitive("circle", "S-GRID-IDEN", f"bubble:y:{row_labels[j]}", center=center, radius=r))
        plan.add(Primitive("mtext", "S-GRID-IDEN", f"label:y:{row_labels[j]}", text=row_labels[j], location=center,
                           height=th, width=0.0, attach="middle_center"))

    columns = []
    if col is not None:
        for i, x in enumerate(xs):
            for j, y in enumerate(ys):
                mark = f"{row_labels[j]}{numbers[i]}"
                pts = rect_points(x - col[0] / 2, y - col[1] / 2, x + col[0] / 2, y + col[1] / 2)
                plan.add(Primitive("polyline", "S-COLS", f"column:{mark}", points=pts, closed=True,
                                   polyline_kind="2d"))
                plan.add(Primitive("hatch", "S-COLS", f"column_fill:{mark}", points=pts, pattern="SOLID"))
                columns.append({"mark": mark, "center": [x, y], "size": list(col)})

    if dimensions:
        gap1, gap2 = ext * 0.5, ext * 0.8
        for i in range(len(xs) - 1):
            plan.add(Primitive("dim_linear", "S-ANNO-DIMS", f"dim:x:{i}", points=((xs[i], y0, 0.0), (xs[i + 1], y0, 0.0)),
                               location=(xs[i], y0 - gap1, 0.0), rotation=0.0))
        if len(xs) > 2:
            plan.add(Primitive("dim_linear", "S-ANNO-DIMS", "dim:x:overall", points=((x0, y0, 0.0), (x1, y0, 0.0)),
                               location=(x0, y0 - gap2, 0.0), rotation=0.0))
        for j in range(len(ys) - 1):
            plan.add(Primitive("dim_linear", "S-ANNO-DIMS", f"dim:y:{j}", points=((x1, ys[j], 0.0), (x1, ys[j + 1], 0.0)),
                               location=(x1 + gap1, ys[j], 0.0), rotation=90.0))
        if len(ys) > 2:
            plan.add(Primitive("dim_linear", "S-ANNO-DIMS", "dim:y:overall", points=((x1, y0, 0.0), (x1, y1, 0.0)),
                               location=(x1 + gap2, y0, 0.0), rotation=90.0))

    plan.meta = {
        "x_lines": [{"label": n, "x": x} for n, x in zip(numbers, xs)],
        "y_lines": [{"label": lab, "y": y} for lab, y in zip(row_labels, ys)],
        "columns": columns,
        "overall": {"x": x1 - x0, "y": y1 - y0},
        "drawing_unit": units.describe(drawing_code),
    }
    return plan
