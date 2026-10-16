"""Sheet border and title block planner (pure).

Draws, in model space, the border of a paper sheet at a plot scale
(1:scale): a sheet of ISO A0-A4, ANSI A-E or ARCH A-E at real paper size
times the scale, a drawing frame inset by the margins (ISO 5457 style: 20 mm
on the binding edge, 10 mm elsewhere), and a title block in the lower-right
corner with labelled fields. Text heights are paper millimetres times the
scale, so they plot at the stated paper size. Nothing here sets up a layout
or plots; use autocad_plot_pdf for that.
"""

from domain import units
from domain.plan import Plan, Primitive, rect_points
from utils import geometry

# (width, height) in millimetres, landscape.
PAPER_SIZES_MM = {
    "A0": (1189.0, 841.0), "A1": (841.0, 594.0), "A2": (594.0, 420.0), "A3": (420.0, 297.0), "A4": (297.0, 210.0),
    "ANSI_A": (279.4, 215.9), "ANSI_B": (431.8, 279.4), "ANSI_C": (558.8, 431.8), "ANSI_D": (863.6, 558.8),
    "ANSI_E": (1117.6, 863.6),
    "ARCH_A": (304.8, 228.6), "ARCH_B": (457.2, 304.8), "ARCH_C": (609.6, 457.2), "ARCH_D": (914.4, 609.6),
    "ARCH_E": (1219.2, 914.4),
}
TITLE_FIELDS = ("project", "title", "drawing_number", "scale", "date", "drawn_by", "checked_by", "sheet", "revision")


def plan_sheet(paper: str, scale: float, drawing_code: int, *, orientation="landscape", origin=(0.0, 0.0),
               fields: dict | None = None, binding_margin_mm=20.0, margin_mm=10.0) -> Plan:
    key = (paper or "").strip().upper().replace("-", "_").replace(" ", "_")
    if key not in PAPER_SIZES_MM:
        raise geometry.ValidationError(f"paper must be one of {sorted(PAPER_SIZES_MM)}, got {paper!r}")
    scale = geometry.validate_positive(scale, "scale")
    if orientation not in ("landscape", "portrait"):
        raise geometry.ValidationError("orientation must be 'landscape' or 'portrait'")
    fields = dict(fields or {})
    unknown = sorted(set(fields) - set(TITLE_FIELDS))
    if unknown:
        raise geometry.ValidationError(f"unknown title block fields {unknown}; allowed: {list(TITLE_FIELDS)}")
    for k, v in fields.items():
        if not isinstance(v, str):
            raise geometry.ValidationError(f"title block field {k!r} must be text")
    fields.setdefault("scale", f"1:{scale:g}")
    ox = geometry.validate_number(origin[0], "origin.x")
    oy = geometry.validate_number(origin[1], "origin.y")

    w_mm, h_mm = PAPER_SIZES_MM[key]
    if orientation == "portrait":
        w_mm, h_mm = h_mm, w_mm
    k = units.convert(1.0, units.unit_code("mm"), drawing_code) * scale  # paper mm -> drawing units

    def p(x_mm, y_mm):
        return (ox + x_mm * k, oy + y_mm * k, 0.0)

    plan = Plan()
    plan.layer("G-ANNO-TTLB", 7)
    plan.layer("G-ANNO-TTLB-TEXT", 7)
    plan.add(Primitive("polyline", "G-ANNO-TTLB", "sheet:edge", closed=True, polyline_kind="2d",
                       points=tuple(p(*q[:2]) for q in rect_points(0, 0, w_mm, h_mm))))
    left, right, bottom, top = binding_margin_mm, w_mm - margin_mm, margin_mm, h_mm - margin_mm
    plan.add(Primitive("polyline", "G-ANNO-TTLB", "sheet:frame", closed=True, polyline_kind="2d",
                       points=tuple(p(*q[:2]) for q in rect_points(left, bottom, right, top))))

    # Title block 180 x 63 mm, three columns of three fields, lower right inside the frame.
    tb_w, tb_h = min(180.0, right - left), 63.0
    tx0, ty0 = right - tb_w, bottom
    plan.add(Primitive("polyline", "G-ANNO-TTLB", "title:box", closed=True, polyline_kind="2d",
                       points=tuple(p(*q[:2]) for q in rect_points(tx0, ty0, right, ty0 + tb_h))))
    rows, cols = 3, 3
    cell_w, cell_h = tb_w / cols, tb_h / rows
    for r in range(1, rows):
        plan.add(Primitive("line", "G-ANNO-TTLB", f"title:row:{r}", points=(p(tx0, ty0 + r * cell_h), p(right, ty0 + r * cell_h))))
    for c in range(1, cols):
        plan.add(Primitive("line", "G-ANNO-TTLB", f"title:col:{c}", points=(p(tx0 + c * cell_w, ty0), p(tx0 + c * cell_w, ty0 + tb_h))))
    label_h, value_h = 2.5, 3.5
    order = ("project", "title", "drawing_number", "scale", "date", "sheet", "drawn_by", "checked_by", "revision")
    for index, name in enumerate(order):
        r, c = 2 - index // cols, index % cols
        x, y = tx0 + c * cell_w + 2.0, ty0 + (r + 1) * cell_h - 2.0
        plan.add(Primitive("mtext", "G-ANNO-TTLB-TEXT", f"title:label:{name}", text=name.replace("_", " ").upper(),
                           location=p(x, y), height=label_h * k, width=0.0))
        value = fields.get(name, "")
        if value:
            plan.add(Primitive("mtext", "G-ANNO-TTLB-TEXT", f"title:value:{name}", text=value,
                               location=p(x, y - label_h - 3.0), height=value_h * k, width=(cell_w - 4.0) * k))
    plan.meta = {
        "paper": key, "orientation": orientation, "paper_mm": [w_mm, h_mm], "scale": scale,
        "sheet_size_drawing_units": [w_mm * k, h_mm * k],
        "drawing_area": {"min": list(p(left, bottom)[:2]), "max": list(p(right, top)[:2]),
                         "title_block_min": list(p(tx0, ty0)[:2])},
        "fields": fields, "drawing_unit": units.describe(drawing_code),
    }
    return plan
