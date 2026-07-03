"""Drawing -> multi-layer SVG.

Coordinates are converted from working-pixel space to page millimetres via the
DrawingArea transform, and emitted with an ``mm`` viewBox so the existing
``svg_to_polylines`` parser (web/server.py) consumes the output unchanged. Each
pen becomes an Inkscape layer group so multi-pen plots stay separable.
"""

from __future__ import annotations

import copy
from xml.etree import ElementTree as ET

from .geometry import Drawing, Layer

_SVG_NS = (
    'xmlns="http://www.w3.org/2000/svg" '
    'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'
)

_SVG_URI = "http://www.w3.org/2000/svg"
_INK_URI = "http://www.inkscape.org/namespaces/inkscape"


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


def _lines_group(pen, lines) -> str:
    """One Inkscape pen layer for a flat list of polylines (already in mm)."""
    colour = getattr(pen, "colour", "#000000")
    stroke_mm = max(0.05, getattr(pen, "stroke_mm", 0.5))
    name = getattr(pen, "name", "Pen")
    body = []
    for line in lines:
        if len(line) < 2:
            continue
        d = " ".join(("M" if i == 0 else "L") + f"{_fmt(x)},{_fmt(y)}"
                     for i, (x, y) in enumerate(line))
        body.append(f'<path d="{d}"/>')
    return (
        f'<g inkscape:groupmode="layer" inkscape:label="{name}" '
        f'fill="none" stroke="{colour}" stroke-width="{_fmt(stroke_mm)}" '
        f'stroke-linecap="round" stroke-linejoin="round">\n' + "\n".join(body) + "\n</g>"
    )


def lines_to_svg_layers(pen_lines, w_mm: float, h_mm: float) -> str:
    """Multi-pen SVG for generators: one Inkscape layer group per pen.

    ``pen_lines`` is a list of ``(pen, list[Line])``; pens with no drawable lines
    are skipped. Mirrors the PFM multi-layer structure so export/parsing are
    unchanged.
    """
    groups = [
        _lines_group(pen, lines)
        for pen, lines in pen_lines
        if any(len(ln) >= 2 for ln in lines)
    ]
    return (
        f'<svg {_SVG_NS} width="{_fmt(w_mm)}mm" height="{_fmt(h_mm)}mm" '
        f'viewBox="0 0 {_fmt(w_mm)} {_fmt(h_mm)}">\n' + "\n".join(groups) + "\n</svg>"
    )


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _pen_label(el) -> str | None:
    """The Inkscape layer label, however the parser namespaced it."""
    return (el.get(f"{{{_INK_URI}}}label")
            or el.get("inkscape:label")
            or el.get("label"))


# Drawable leaf shapes a split can assign to a pen. Non-drawable containers
# (<g>, <defs>, …) are never assigned directly.
_DRAWABLES = ("path", "circle", "ellipse", "rect", "line", "polyline", "polygon")
# Subtrees whose geometry is definitional, not drawn: never a pen's shape.
_SKIP_ANCESTORS = ("defs", "clipPath", "mask", "symbol", "marker")
_ASSIGN_ATTR = "__pen_assign__"  # scratch tag, stripped before serialize


def _under_skip(el, parent_map) -> bool:
    node = parent_map.get(el)
    while node is not None:
        if _local(node.tag) in _SKIP_ANCESTORS:
            return True
        node = parent_map.get(node)
    return False


def _label_ancestor(el, parent_map) -> str | None:
    """Nearest inkscape:label on the element or an ancestor (labels win)."""
    node = el
    while node is not None:
        lbl = _pen_label(node)
        if lbl is not None:
            return lbl
        node = parent_map.get(node)
    return None


def _effective_colour(el, parent_map) -> str:
    """Element's drawn colour: own/inherited ``stroke`` (ignoring ``none``),
    else ``fill``, else black. Presentation attributes only (no CSS ``style``)."""
    node = el
    stroke = fill = None
    while node is not None:
        if stroke is None:
            s = node.get("stroke")
            if s and s.strip().lower() != "none":
                stroke = s
        if fill is None:
            f = node.get("fill")
            if f and f.strip().lower() != "none":
                fill = f
        node = parent_map.get(node)
    return stroke or fill or "#000000"


def _nearest_label(colour, pen_order) -> str | None:
    """Name of the pen whose colour is nearest ``colour`` (sRGB euclidean)."""
    from .pens import hex_to_rgb
    r, g, b = hex_to_rgb(colour)
    best = None
    best_d = None
    for name, pcol in pen_order:
        pr, pg, pb = hex_to_rgb(pcol)
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if best_d is None or d < best_d:
            best_d, best = d, name
    return best


def split_svg_by_pen(svg_bytes, pen_order):
    """Split a composed multi-layer SVG into one SVG per pen.

    Two kinds of drawable are assigned to a pen:

    * Geometry inside an Inkscape layer group
      (``<g inkscape:label="{pen}">``, produced by ``_render_layer`` /
      ``_lines_group``) keeps that label — labels always win.
    * Any other drawable (raw imported/cavalry markup with no label) is matched
      to the nearest enabled pen by its effective colour (own/inherited stroke,
      else fill, else black). This is what lets unlabelled Cavalry strokes plot
      per pen instead of being silently dropped.

    ``pen_order`` is a list of ``(name, colour)`` (the enabled pen list, in
    order). With no pens, unlabelled content stays unassigned (preserving the
    "no pens → []" contract). Each returned SVG is the whole document with other
    pens' drawables removed, so ancestor transforms, ``<defs>`` and ``clip-path``
    refs (cavalry masks) and native ``<circle>`` fast paths are all preserved.
    Returns ``[{"name", "colour", "shapes", "svg"}]`` ordered by ``pen_order``
    first, then any leftover labels.
    """
    if isinstance(svg_bytes, str):
        svg_bytes = svg_bytes.encode("utf-8")
    root = ET.fromstring(svg_bytes)
    parent = {child: el for el in root.iter() for child in el}
    pen_order = pen_order or []
    pen_colours = dict(pen_order)

    # Pass 1 — assign each drawable a pen label, tagging it in place.
    buckets: dict[str, dict] = {}
    order_seen: list[str] = []
    for el in root.iter():
        if _local(el.tag) not in _DRAWABLES:
            continue
        if _under_skip(el, parent):
            continue
        label = _label_ancestor(el, parent)
        if label is None:
            if not pen_order:
                continue  # unlabelled + no pens → dropped (legacy contract)
            label = _nearest_label(_effective_colour(el, parent), pen_order)
            if label is None:
                continue
        el.set(_ASSIGN_ATTR, label)
        b = buckets.get(label)
        if b is None:
            b = {"colour": pen_colours.get(label)
                 or _effective_colour(el, parent), "shapes": 0}
            buckets[label] = b
            order_seen.append(label)
        b["shapes"] += 1

    if not buckets:
        return []

    # Order: pen_order labels first (matched by name), then leftovers as seen.
    ordered_labels: list[str] = []
    for name, _colour in pen_order:
        if name in buckets and name not in ordered_labels:
            ordered_labels.append(name)
    for label in order_seen:
        if label not in ordered_labels:
            ordered_labels.append(label)

    ET.register_namespace("", _SVG_URI)
    ET.register_namespace("inkscape", _INK_URI)

    # Pass 2 — emit: one whole-document copy per pen with other pens' drawables
    # removed. Serializing the whole root keeps transforms / defs / clip refs.
    out = []
    for label in ordered_labels:
        dup = copy.deepcopy(root)
        dparent = {child: el for el in dup.iter() for child in el}
        for el in list(dup.iter()):
            assigned = el.get(_ASSIGN_ATTR)
            if assigned is not None and assigned != label:
                p = dparent.get(el)
                if p is not None:
                    p.remove(el)
        for el in dup.iter():
            el.attrib.pop(_ASSIGN_ATTR, None)
        out.append({
            "name": label,
            "colour": buckets[label]["colour"],
            "shapes": buckets[label]["shapes"],
            "svg": ET.tostring(dup, encoding="unicode"),
        })
    return out


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
