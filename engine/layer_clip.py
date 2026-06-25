"""Geometric crop/mask baking for composition layers.

Composition layers are positioned on the page assuming 1 SVG user-unit = 1 mm
(see ``engine.composition``). The plot/export pipeline parses the composed SVG
with *svgelements*, which ignores ``<clipPath>`` — so any crop or mask has to be
applied as real line clipping, not an SVG clip attribute.

This module flattens a layer's SVG to stroked polylines in **layer-local mm**
(no Y-flip, origin at the layer's top-left), clips them to the crop rectangle
and/or mask polygon, and re-emits ``<path>`` elements. Coordinates match the
frontend's drawing space and ``parse_svg_size_mm``.
"""

from __future__ import annotations

import math
from xml.sax.saxutils import escape

from .geometry import Point, clip_polyline, clip_polyline_polygon

PX_TO_MM = 25.4 / 96.0
_STEP_MM = 0.4  # curve flattening resolution


def _fmt(value: float) -> str:
    return f"{float(value):.3f}".rstrip("0").rstrip(".")


def _se():
    try:
        import svgelements as se
    except ImportError as exc:  # pragma: no cover - dependency guaranteed in prod
        raise RuntimeError("svgelements not installed. Run: uv add svgelements") from exc
    return se


def _drawables(svg: str):
    se = _se()
    doc = se.SVG.parse(_io_for(svg), reify=True)
    return [el for el in doc.elements() if not isinstance(el, (se.Group, se.SVG))], se


def _io_for(svg: str):
    import io

    return io.BytesIO(svg.encode("utf-8"))


def layer_content_bbox(svg: str) -> tuple[float, float, float, float] | None:
    """Bounding box of all drawn geometry in layer-local mm, or None if empty."""
    drawables, _se = _drawables(svg)
    xs0: list[float] = []
    ys0: list[float] = []
    xs1: list[float] = []
    ys1: list[float] = []
    for el in drawables:
        try:
            box = el.bbox()
        except Exception:
            box = None
        if not box:
            continue
        x0, y0, x1, y1 = box
        xs0.append(x0)
        ys0.append(y0)
        xs1.append(x1)
        ys1.append(y1)
    if not xs0:
        return None
    return (
        min(xs0) * PX_TO_MM,
        min(ys0) * PX_TO_MM,
        max(xs1) * PX_TO_MM,
        max(ys1) * PX_TO_MM,
    )


def _stroke_attrs(el) -> str:
    stroke = getattr(el, "stroke", None)
    color = "#000000"
    if stroke is not None and getattr(stroke, "value", None) is not None:
        try:
            color = stroke.hex
        except Exception:
            color = "#000000"
    width = getattr(el, "stroke_width", None)
    parts = [f'stroke="{color}"', 'fill="none"']
    if width:
        parts.append(f'stroke-width="{_fmt(float(width) * PX_TO_MM)}"')
    return " ".join(parts)


def _flatten_element(el) -> list[list[Point]]:
    """Sample one element to a list of polylines in layer-local mm (no Y-flip)."""
    try:
        segs = list(el.segments())
    except Exception:
        return []
    step_px = _STEP_MM / PX_TO_MM
    polylines: list[list[Point]] = []
    current: list[Point] = []

    def push():
        if len(current) >= 2:
            polylines.append(current.copy())

    for seg in segs:
        name = type(seg).__name__
        if name == "Move":
            push()
            current.clear()
            p = seg.end
            current.append((p.x * PX_TO_MM, p.y * PX_TO_MM))
        elif name == "Close":
            if current:
                current.append(current[0])
            push()
            current.clear()
        elif name == "Line":
            p = seg.end
            current.append((p.x * PX_TO_MM, p.y * PX_TO_MM))
        else:
            # CubicBezier / QuadraticBezier / Arc / anything else — sample by length
            try:
                length = seg.length()
            except Exception:
                length = step_px
            n = max(1, int(length / step_px))
            for i in range(1, n + 1):
                p = seg.point(i / n)
                current.append((p.x * PX_TO_MM, p.y * PX_TO_MM))
    push()
    return polylines


def mask_polygon(mask: dict) -> list[Point]:
    """Convert a mask shape (layer-local mm) to a closed polygon ring."""
    kind = mask.get("type")
    if kind == "rect":
        x = float(mask["x"])
        y = float(mask["y"])
        w = float(mask["width"])
        h = float(mask["height"])
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    if kind == "ellipse":
        cx = float(mask["cx"])
        cy = float(mask["cy"])
        rx = float(mask["rx"])
        ry = float(mask["ry"])
        n = max(24, int(2 * math.pi * max(rx, ry) / _STEP_MM))
        n = min(n, 512)
        return [
            (cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n))
            for i in range(n)
        ]
    if kind == "path":
        # The mask ``d`` is authored directly in layer-local mm (no document
        # viewBox), so svgelements coordinates are already mm — no px scaling.
        se = _se()
        path = se.Path(str(mask.get("d", "")))
        pts: list[Point] = []
        try:
            length = path.length()
        except Exception:
            length = 0
        n = max(32, int(length / _STEP_MM)) if length else 64
        n = min(n, 4096)
        for i in range(n):
            p = path.point(i / n)
            pts.append((p.x, p.y))
        return pts
    return []


def _crop_rect(crop: dict) -> tuple[float, float, float, float]:
    x = float(crop["x"])
    y = float(crop["y"])
    return (x, y, x + float(crop["width"]), y + float(crop["height"]))


def clipped_layer_body(svg: str, crop: dict | None, mask: dict | None) -> str:
    """Flatten ``svg`` and clip to ``crop`` and/or ``mask``; return SVG body.

    Coordinates are layer-local mm; the caller wraps this in the layer's
    ``translate(x y)`` (or a crop offset for split export).
    """
    rect = _crop_rect(crop) if crop else None
    poly = mask_polygon(mask) if mask else None
    drawables, _se = _drawables(svg)
    out: list[str] = []
    for el in drawables:
        attrs = _stroke_attrs(el)
        for line in _flatten_element(el):
            pieces = [line]
            if rect is not None:
                pieces = [sub for pl in pieces for sub in clip_polyline(pl, rect)]
            if poly:
                pieces = [sub for pl in pieces for sub in clip_polyline_polygon(pl, poly)]
            for sub in pieces:
                if len(sub) < 2:
                    continue
                d = "M" + " L".join(f"{_fmt(x)} {_fmt(y)}" for x, y in sub)
                out.append(f'<path d="{escape(d)}" {attrs}/>')
    return "\n".join(out)
