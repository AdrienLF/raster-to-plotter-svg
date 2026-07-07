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
import re
from xml.sax.saxutils import escape

from .geometry import Point, _segment_polygon_ts, clip_polyline, clip_polyline_polygon, point_in_polygon

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


_PATH_TOKEN = re.compile(r"[A-Za-z]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _polygon_from_ml_path(d: str) -> list[Point] | None:
    """Exact vertices of an absolute M/L(/Z) polygon, or None to fall back.

    Region occlusion masks are emitted as absolute ``M x,y L x,y … Z`` polygons
    (web/server.py), already corner-simplified. Take those vertices verbatim
    instead of resampling. Anything else (curves, relative ops, H/V) returns
    None so the caller resamples with svgelements.
    """
    tokens = _PATH_TOKEN.findall(d)
    pts: list[Point] = []
    cmd = None
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in ("Z", "z"):
                continue
            if cmd not in ("M", "L"):
                return None  # curves / relative / H / V — not a plain polygon
            continue
        if cmd not in ("M", "L"):
            return None
        try:
            pts.append((float(tokens[i]), float(tokens[i + 1])))
        except (IndexError, ValueError):
            return None
        i += 2
    return pts if len(pts) >= 3 else None


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
        d = str(mask.get("d", ""))
        # Fast path: a plain M/L polygon (the common region-mask case) is taken
        # verbatim — no resampling, no rounded corners.
        exact = _polygon_from_ml_path(d)
        if exact is not None:
            return exact
        # The mask ``d`` is authored directly in layer-local mm (no document
        # viewBox), so svgelements coordinates are already mm — no px scaling.
        se = _se()
        path = se.Path(d)
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


def _polygon_bbox(pts: list[Point]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_disjoint(a, b) -> bool:
    return a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1]


def _crop_rect(crop: dict) -> tuple[float, float, float, float]:
    x = float(crop["x"])
    y = float(crop["y"])
    return (x, y, x + float(crop["width"]), y + float(crop["height"]))


def _clip_polyline_outside_polygon(points: list[Point], polygon: list[Point]) -> list[list[Point]]:
    """Return sub-polylines that fall outside ``polygon``."""
    if len(polygon) < 3 or len(points) < 2:
        return [points]
    out: list[list[Point]] = []
    current: list[Point] = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        cuts = sorted(set(_segment_polygon_ts(x0, y0, x1, y1, polygon)))
        bounds = [0.0] + cuts + [1.0]
        dx, dy = x1 - x0, y1 - y0
        for ta, tb in zip(bounds, bounds[1:]):
            if tb - ta < 1e-9:
                continue
            tm = (ta + tb) / 2
            if point_in_polygon((x0 + tm * dx, y0 + tm * dy), polygon):
                if len(current) >= 2:
                    out.append(current)
                current = []
                continue
            a = (x0 + ta * dx, y0 + ta * dy)
            b = (x0 + tb * dx, y0 + tb * dy)
            if not current:
                current = [a, b]
            elif current[-1] == a:
                current.append(b)
            else:
                if len(current) >= 2:
                    out.append(current)
                current = [a, b]
    if len(current) >= 2:
        out.append(current)
    return out


def flattened_clipped_polylines(
    svg: str,
    crop: dict | None,
    mask: dict | None,
) -> list[tuple[list[Point], str, float]]:
    """Flatten ``svg`` and clip to ``crop`` and/or ``mask``.

    Returns ``(polyline, stroke_attrs, stroke_width_mm)`` tuples in layer-local
    mm — the shared front half of :func:`clipped_layer_body`, also used by the
    stroke-occlusion pass in ``engine.composition`` (width 0.0 = unparsable).
    """
    rect = _crop_rect(crop) if crop else None
    poly = mask_polygon(mask) if mask else None
    poly_bb = _polygon_bbox(poly) if poly else None
    drawables, _se = _drawables(svg)
    out: list[tuple[list[Point], str, float]] = []
    for el in drawables:
        attrs = _stroke_attrs(el)
        width = getattr(el, "stroke_width", None)
        width_mm = float(width) * PX_TO_MM if width else 0.0
        for line in _flatten_element(el):
            pieces = [line]
            if rect is not None:
                pieces = [sub for pl in pieces for sub in clip_polyline(pl, rect)]
            if poly:
                kept = []
                for pl in pieces:
                    # Disjoint from the inclusion mask's bbox => wholly outside.
                    if _bbox_disjoint(_polygon_bbox(pl), poly_bb):
                        continue
                    kept.extend(clip_polyline_polygon(pl, poly))
                pieces = kept
            for sub in pieces:
                if len(sub) >= 2:
                    out.append((sub, attrs, width_mm))
    return out


def polyline_path_el(points: list[Point], attrs: str) -> str:
    """One ``<path>`` element for a layer-local-mm polyline."""
    d = "M" + " L".join(f"{_fmt(x)} {_fmt(y)}" for x, y in points)
    return f'<path d="{escape(d)}" {attrs}/>'


def clipped_layer_body(
    svg: str,
    crop: dict | None,
    mask: dict | None,
    exclude_masks: list[dict] | None = None,
) -> str:
    """Flatten ``svg`` and clip to ``crop`` and/or ``mask``; return SVG body.

    Coordinates are layer-local mm; the caller wraps this in the layer's
    ``translate(x y)`` (or a crop offset for split export).
    """
    exclude_polys = [mask_polygon(m) for m in (exclude_masks or []) if m]
    # (polygon, bbox) for each occluder, so a polyline whose bbox misses the
    # occluder can be kept untouched without the O(segments x edges) clip.
    exclude_data = [(p, _polygon_bbox(p)) for p in exclude_polys if p]
    out: list[str] = []
    for line, attrs, _width in flattened_clipped_polylines(svg, crop, mask):
        pieces = [line]
        for exclude_poly, ebb in exclude_data:
            kept = []
            for pl in pieces:
                # Disjoint from the occluder's bbox => nothing to remove.
                if _bbox_disjoint(_polygon_bbox(pl), ebb):
                    kept.append(pl)
                else:
                    kept.extend(_clip_polyline_outside_polygon(pl, exclude_poly))
            pieces = kept
        for sub in pieces:
            if len(sub) < 2:
                continue
            out.append(polyline_path_el(sub, attrs))
    return "\n".join(out)
