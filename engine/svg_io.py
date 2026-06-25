"""Drawing -> multi-layer SVG.

Coordinates are converted from working-pixel space to page millimetres via the
DrawingArea transform, and emitted with an ``mm`` viewBox so the existing
``svg_to_polylines`` parser (web/server.py) consumes the output unchanged. Each
pen becomes an Inkscape layer group so multi-pen plots stay separable.
"""

from __future__ import annotations

from .geometry import Drawing, Layer

_SVG_NS = (
    'xmlns="http://www.w3.org/2000/svg" '
    'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'
)


def _fmt(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".")


def _path_d(points, scale_fn) -> str:
    parts = []
    for i, (x, y) in enumerate(points):
        mx, my = scale_fn(x, y)
        parts.append(("M" if i == 0 else "L") + f"{_fmt(mx)},{_fmt(my)}")
    return " ".join(parts)


def _render_layer(layer: Layer, scale_fn, scale: float) -> str:
    pen = layer.pen
    colour = getattr(pen, "colour", "#000000")
    stroke_mm = max(0.05, getattr(pen, "stroke_mm", 0.5))
    name = getattr(pen, "name", "Pen")

    body = [
        f'<g inkscape:groupmode="layer" inkscape:label="{name}" '
        f'fill="none" stroke="{colour}" stroke-width="{_fmt(stroke_mm)}" '
        f'stroke-linecap="round" stroke-linejoin="round">'
    ]
    for d in layer.dots:
        cx, cy = scale_fn(d.x, d.y)
        body.append(
            f'<circle cx="{_fmt(cx)}" cy="{_fmt(cy)}" r="{_fmt(d.r * scale)}" '
            f'fill="{colour}" stroke="none"/>'
        )
    for g in layer.paths:
        pts = g.points + [g.points[0]] if g.closed and g.points else g.points
        if len(pts) >= 2:
            body.append(f'<path d="{_path_d(pts, scale_fn)}"/>')
    body.append("</g>")
    return "\n".join(body)


def to_svg(drawing: Drawing) -> str:
    """Full multi-layer SVG string for the whole drawing."""
    w_mm, h_mm = drawing.area.page_size_mm()
    scale_fn, scale = drawing.area.px_to_mm(drawing.width, drawing.height)
    layers = "\n".join(_render_layer(l, scale_fn, scale) for l in drawing.layers if l.count())
    return (
        f'<svg {_SVG_NS} width="{_fmt(w_mm)}mm" height="{_fmt(h_mm)}mm" '
        f'viewBox="0 0 {_fmt(w_mm)} {_fmt(h_mm)}">\n{layers}\n</svg>'
    )


def to_svg_layers(drawing: Drawing) -> list[tuple[str, str]]:
    """One SVG per non-empty pen layer: list of (pen_name, svg_string)."""
    w_mm, h_mm = drawing.area.page_size_mm()
    scale_fn, scale = drawing.area.px_to_mm(drawing.width, drawing.height)
    out = []
    for layer in drawing.layers:
        if not layer.count():
            continue
        body = _render_layer(layer, scale_fn, scale)
        svg = (
            f'<svg {_SVG_NS} width="{_fmt(w_mm)}mm" height="{_fmt(h_mm)}mm" '
            f'viewBox="0 0 {_fmt(w_mm)} {_fmt(h_mm)}">\n{body}\n</svg>'
        )
        out.append((getattr(layer.pen, "name", "Pen"), svg))
    return out


def lines_to_svg(lines, w_mm: float, h_mm: float,
                 colour: str = "#000000", stroke_mm: float = 0.3) -> str:
    """SVG for a flat list of polylines already in page millimetres (generators)."""
    body = []
    for line in lines:
        if len(line) < 2:
            continue
        d = " ".join(("M" if i == 0 else "L") + f"{_fmt(x)},{_fmt(y)}"
                     for i, (x, y) in enumerate(line))
        body.append(f'<path d="{d}"/>')
    group = (
        f'<g fill="none" stroke="{colour}" stroke-width="{_fmt(stroke_mm)}" '
        f'stroke-linecap="round" stroke-linejoin="round">\n' + "\n".join(body) + "\n</g>"
    )
    return (
        f'<svg {_SVG_NS} width="{_fmt(w_mm)}mm" height="{_fmt(h_mm)}mm" '
        f'viewBox="0 0 {_fmt(w_mm)} {_fmt(h_mm)}">\n{group}\n</svg>'
    )


def lines_length_mm(lines) -> float:
    import math
    total = 0.0
    for line in lines:
        for (x0, y0), (x1, y1) in zip(line, line[1:]):
            total += math.hypot(x1 - x0, y1 - y0)
    return total


def estimate_path_length_mm(drawing: Drawing) -> float:
    """Rough pen-down travel estimate in mm (for the status bar)."""
    import math
    _, scale = drawing.area.px_to_mm(drawing.width, drawing.height)
    total = 0.0
    for layer in drawing.layers:
        for d in layer.dots:
            total += 2 * math.pi * d.r * scale
        for g in layer.paths:
            pts = g.points
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                total += math.hypot(x1 - x0, y1 - y0) * scale
    return total
