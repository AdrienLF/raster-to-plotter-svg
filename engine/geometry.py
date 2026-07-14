"""Geometry model.

During PFM generation everything lives in *working-pixel* coordinates (the
working raster the sampler analysed). ``svg_io`` applies the DrawingArea
pixel->mm transform when writing the final SVG, so the engine never has to
think in mm until export.

A ``Dot`` is kept distinct from a polyline ``Geometry`` so stipple output can be
written as compact ``<circle>`` elements (matching the existing exporter) rather
than polygonised paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Point = tuple[float, float]


@dataclass
class Geometry:
    """An open or closed polyline in working-pixel coordinates.

    ``colour``/``fill`` are optional per-path presentation overrides (hex
    strings); when unset the path inherits its pen layer's stroke and no fill.
    """

    points: list[Point]
    closed: bool = False
    colour: str | None = None
    fill: str | None = None

    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return min(xs), min(ys), max(xs), max(ys)


@dataclass
class Dot:
    x: float
    y: float
    r: float


@dataclass
class Item:
    """One generated unit before pen assignment.

    ``lum`` is the sampled darkness (0 = light, 1 = dark) used by luminance-
    weighted pen distribution. Exactly one of ``dot``/``path`` is set.
    """

    lum: float
    dot: Dot | None = None
    path: Geometry | None = None


@dataclass
class Layer:
    """Geometry assigned to a single pen."""

    pen: "object"                    # engine.pens.Pen (avoid import cycle)
    dots: list[Dot] = field(default_factory=list)
    paths: list[Geometry] = field(default_factory=list)

    def count(self) -> int:
        return len(self.dots) + len(self.paths)


@dataclass
class Drawing:
    """Working-pixel-space result of a PFM run."""

    width: int                       # working raster width (px)
    height: int                      # working raster height (px)
    area: "object"                   # engine.canvas.DrawingArea
    layers: list[Layer] = field(default_factory=list)
    background: str | None = None    # page background colour (export-only, never plotted)

    def total(self) -> int:
        return sum(l.count() for l in self.layers)

    def bbox(self) -> tuple[float, float, float, float]:
        xs: list[float] = []
        ys: list[float] = []
        for layer in self.layers:
            for d in layer.dots:
                xs += [d.x - d.r, d.x + d.r]
                ys += [d.y - d.r, d.y + d.r]
            for g in layer.paths:
                for x, y in g.points:
                    xs.append(x)
                    ys.append(y)
        if not xs:
            return 0.0, 0.0, float(self.width), float(self.height)
        return min(xs), min(ys), max(xs), max(ys)


# ── Clipping (Liang–Barsky for segments) ───────────────────────────────────────

def _clip_segment(
    x0: float, y0: float, x1: float, y1: float,
    xmin: float, ymin: float, xmax: float, ymax: float,
) -> tuple[Point, Point] | None:
    """Clip a single segment to a rectangle. Returns endpoints or None."""
    dx = x1 - x0
    dy = y1 - y0
    p = [-dx, dx, -dy, dy]
    q = [x0 - xmin, xmax - x0, y0 - ymin, ymax - y0]
    u0, u1 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return None        # parallel and outside
        else:
            t = qi / pi
            if pi < 0:
                if t > u1:
                    return None
                if t > u0:
                    u0 = t
            else:
                if t < u0:
                    return None
                if t < u1:
                    u1 = t
    nx0, ny0 = x0 + u0 * dx, y0 + u0 * dy
    nx1, ny1 = x0 + u1 * dx, y0 + u1 * dy
    return (nx0, ny0), (nx1, ny1)


def clip_polyline(points: list[Point], rect: tuple[float, float, float, float]) -> list[list[Point]]:
    """Clip an open polyline to a rectangle, returning a list of sub-polylines."""
    xmin, ymin, xmax, ymax = rect
    out: list[list[Point]] = []
    current: list[Point] = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        clipped = _clip_segment(x0, y0, x1, y1, xmin, ymin, xmax, ymax)
        if clipped is None:
            if len(current) >= 2:
                out.append(current)
            current = []
            continue
        a, b = clipped
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


# ── Clipping (general polygon) ──────────────────────────────────────────────────

def point_in_polygon(pt: Point, poly: list[Point]) -> bool:
    """Even-odd ray-cast test. ``poly`` is a list of vertices (open ring)."""
    x, y = pt
    inside = False
    n = len(poly)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            x_cross = xi + (y - yi) * (xj - xi) / (yj - yi)
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def _segment_polygon_ts(
    ax: float, ay: float, bx: float, by: float, poly: list[Point]
) -> list[float]:
    """Parameters t in (0,1) where segment a→b crosses any edge of ``poly``."""
    rx, ry = bx - ax, by - ay
    ts: list[float] = []
    n = len(poly)
    for i in range(n):
        cx, cy = poly[i]
        dx_, dy_ = poly[(i + 1) % n]
        sx, sy = dx_ - cx, dy_ - cy
        denom = rx * sy - ry * sx
        if denom == 0:
            continue  # parallel / collinear — midpoint test still classifies sub-spans
        t = ((cx - ax) * sy - (cy - ay) * sx) / denom
        u = ((cx - ax) * ry - (cy - ay) * rx) / denom
        if 0.0 <= u <= 1.0 and 0.0 < t < 1.0:
            ts.append(t)
    return ts


def clip_polyline_polygon(points: list[Point], polygon: list[Point]) -> list[list[Point]]:
    """Clip an open polyline to an arbitrary (possibly concave) closed polygon.

    Returns the list of sub-polylines that fall inside ``polygon``.
    """
    if len(polygon) < 3 or len(points) < 2:
        return []
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
            if not point_in_polygon((x0 + tm * dx, y0 + tm * dy), polygon):
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


def clip_drawing(drawing: Drawing, rect: tuple[float, float, float, float]) -> None:
    """In-place clip of every layer's geometry to ``rect`` (working-pixel coords)."""
    xmin, ymin, xmax, ymax = rect
    for layer in drawing.layers:
        layer.dots = [d for d in layer.dots if xmin <= d.x <= xmax and ymin <= d.y <= ymax]
        new_paths: list[Geometry] = []
        for g in layer.paths:
            pts = g.points + [g.points[0]] if g.closed and len(g.points) >= 2 else g.points
            for sub in clip_polyline(pts, rect):
                new_paths.append(Geometry(sub, closed=False, colour=g.colour, fill=g.fill))
        layer.paths = new_paths
