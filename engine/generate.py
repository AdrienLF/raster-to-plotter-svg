"""Rule-based drawing generators (the "Generate" step).

Port of revdancatt-style pen-plotter generators. These take no input image —
they build geometry directly from parameters and output polylines in mm.

First generator: Spokes & Circles — a sunburst of rays plus rings of concentric
circles, with the rays culled out from inside each circle cluster.
"""

from __future__ import annotations

import math
import random
from copy import deepcopy

from .geometry import clip_polyline
from .genframe import FRAMEWORK_PARAMS, convex_interval
from .params import Param
from .shape_field import (
    DEFAULT_SHAPE_LAYERS,
    SHAPE_FIELD_PARAMS,
    SHAPE_TYPES,
    normalize_shape_field_params,
    shape_field,
)

Line = list[tuple[float, float]]


# ── geometry helpers (work in the generator's own units, origin top-left) ───────

def rotate(pts: Line, deg: float) -> Line:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [(x * c - y * s, x * s + y * c) for x, y in pts]


def translate(pts: Line, dx: float, dy: float) -> Line:
    return [(x + dx, y + dy) for x, y in pts]


def make_circle(segments: int, radius: float) -> Line:
    segments = max(3, int(segments))
    return [(radius * math.cos(2 * math.pi * i / segments),
             radius * math.sin(2 * math.pi * i / segments))
            for i in range(segments + 1)]


def _clip_lines_to_rect(lines: list[Line], rect: tuple[float, float, float, float],
                        tags=None):
    out: list[Line] = []
    out_tags: list | None = [] if tags is not None else None
    for i, line in enumerate(lines):
        for sub in clip_polyline(line, rect):
            out.append(sub)
            if out_tags is not None:
                out_tags.append(tags[i])
    return (out, out_tags) if tags is not None else out


def _segment_outside_circle(p0, p1, cx, cy, r):
    """Return the sub-segments of p0->p1 that lie OUTSIDE the circle."""
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = x1 - x0, y1 - y0
    fx, fy = x0 - cx, y0 - cy
    a = dx * dx + dy * dy
    if a == 0:
        return [] if (fx * fx + fy * fy) < r * r else [(p0, p1)]
    b = 2 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - r * r
    disc = b * b - 4 * a * c

    def at(t):
        return (x0 + dx * t, y0 + dy * t)

    if disc <= 0:
        mx, my = x0 + dx * 0.5, y0 + dy * 0.5
        return [] if (mx - cx) ** 2 + (my - cy) ** 2 < r * r else [(p0, p1)]
    sd = math.sqrt(disc)
    t1 = (-b - sd) / (2 * a)
    t2 = (-b + sd) / (2 * a)
    out = []
    if t1 > 0:
        out.append((at(0.0), at(min(t1, 1.0))))
    if t2 < 1:
        out.append((at(max(t2, 0.0)), at(1.0)))
    return out


def cull_inside_polygon(lines: list[Line], poly: Line, tags=None):
    """Remove the parts of each line that fall inside the convex polygon.

    When ``tags`` (a per-line list) is given, every kept sub-line inherits its
    source line's tag and ``(out, out_tags)`` is returned.
    """
    out: list[Line] = []
    out_tags: list | None = [] if tags is not None else None

    def keep(sub, tag):
        out.append(sub)
        if out_tags is not None:
            out_tags.append(tag)

    for i, line in enumerate(lines):
        tag = tags[i] if tags is not None else None
        for p0, p1 in zip(line, line[1:]):
            iv = convex_interval(p0, p1, poly)
            if iv is None:               # segment entirely outside -> keep it
                keep([p0, p1], tag)
                continue
            u0, u1 = iv
            x0, y0 = p0
            dx, dy = p1[0] - x0, p1[1] - y0
            if u0 > 0:
                keep([(x0, y0), (x0 + dx * u0, y0 + dy * u0)], tag)
            if u1 < 1:
                keep([(x0 + dx * u1, y0 + dy * u1), (p1[0], p1[1])], tag)
    return (out, out_tags) if tags is not None else out


# ── Spokes & Circles ────────────────────────────────────────────────────────────

def spokes_and_circles(p: dict, seed: int = 0):
    """Return (lines_mm, page_w_mm, page_h_mm). Units in are cm (as revdancatt)."""
    rng = random.Random(seed)
    pw, ph = float(p["page_width"]), float(p["page_height"])
    cx_pg, cy_pg = pw / 2, ph / 2
    spokes = max(1, int(p["spokes"]))
    rays = max(0, int(p["rays"]))
    circles = max(0, int(p["circles"]))
    cseg = int(p["circle_segments"])
    spoke_len = float(p["spoke_length"])
    angle = 360.0 / spokes
    circle_step = (float(p["outer_radius"]) / circles) if circles else 0.0

    # full-page sunburst of rays from the centre
    ray_lines: list[Line] = []
    for r in range(rays):
        line = [(0.0, 0.0), (0.0, -ph)]
        line = rotate(line, r * 360.0 / max(1, rays) + float(p["ray_rotation"]))
        line = translate(line, cx_pg, cy_pg)
        ray_lines.append(line)

    rect = (float(p["side_margin"]), float(p["top_bottom_margin"]),
            pw - float(p["side_margin"]), ph - float(p["top_bottom_margin"]))
    ray_lines = _clip_lines_to_rect(ray_lines, rect)

    # Pen-bucket cycling. Each line is tagged with a bucket index (mapped to a real
    # pen by the worker via `bucket % len(active pens)`); None means first/active
    # pen. Buckets count in `pen_order` from `pen_offset`. Spokes and circles use
    # independent counters (both start at the offset).
    cycle = bool(p.get("pen_cycle"))
    step = -1 if p.get("pen_order") == "reverse" else 1
    offset = int(p.get("pen_offset", 0))
    circles_mode = p.get("pen_circles", "per_cluster")
    circle_stagger = max(0, int(p.get("pen_circle_stagger", 0)))
    pen_spokes = bool(p.get("pen_spokes", True))
    rays_bucket = int(p.get("pen_rays", 0))      # absolute pen for the rays
    border_bucket = int(p.get("pen_border", 0))  # absolute pen for drawn outlines

    def bucket(i: int) -> int:
        return offset + step * i

    spoke_lines: list[Line] = []
    spoke_tags: list = []
    if p["draw_spokes"]:
        for s in range(spokes):
            sp_ang = angle * s + 90 + float(p["spoke_rotation"])
            spoke = [(0.0, 0.0), (0.0, -spoke_len)]
            spoke = translate(rotate(spoke, sp_ang), cx_pg, cy_pg)
            spoke_lines.append(spoke)
            spoke_tags.append(bucket(s) if (cycle and pen_spokes) else None)

    circle_lines: list[Line] = []
    circle_tags: list = []
    for s in range(spokes):
        sp_ang = angle * s + 90 + float(p["spoke_rotation"])

        for c in range(1, circles + 1):
            circ = make_circle(cseg, circle_step * c)
            amount = (rng.randrange(cseg) * (360.0 / cseg)) if p["random_circle_start"] else 0.0
            circ = rotate(circ, float(p["circle_rotation"])
                          + (circles - c) * float(p["circle_inner_rotation"]) + amount + 90)
            circ = translate(circ, 0, -spoke_len)
            circ = translate(rotate(circ, sp_ang), cx_pg, cy_pg)
            circle_lines.append(circ)
            if cycle and circles_mode == "per_cluster":
                circle_tags.append(bucket(s))
            elif cycle and circles_mode == "per_ring":
                circle_tags.append(bucket((c - 1) + s * circle_stagger))
            else:
                circle_tags.append(None)

        # cropping shape — a polygon with `circle_segments` sides (matches the
        # rendered circles), so a low segment count crops as a triangle/square.
        crop = make_circle(cseg, float(p["crop_radius"]))
        crop = rotate(crop, float(p["circle_rotation"]) + 90)
        crop = translate(crop, 0, -spoke_len)
        crop = translate(rotate(crop, sp_ang), cx_pg, cy_pg)
        if p["draw_crop_radius"]:
            circle_lines.append(crop)
            circle_tags.append(border_bucket)
        ray_lines = cull_inside_polygon(ray_lines, crop)
        spoke_lines, spoke_tags = cull_inside_polygon(spoke_lines, crop, spoke_tags)

    # spokes first, then circles, then rays (matches the original ordering).
    all_lines = spoke_lines + circle_lines + ray_lines
    all_tags = spoke_tags + circle_tags + [rays_bucket] * len(ray_lines)

    # Output in cm; the framework pipeline + worker handle margins, cropping,
    # transforms and the final cm -> mm conversion.
    lines: list[Line] = []
    line_pens: list = []
    for line, tag in zip(all_lines, all_tags):
        if len(line) >= 2:
            lines.append(line)
            line_pens.append(tag)
    # Stay a 3-tuple unless pen cycling is on, so existing callers are unaffected.
    if cycle:
        return lines, pw, ph, line_pens
    return lines, pw, ph


# ── registry ────────────────────────────────────────────────────────────────────

_SPOKES_PARAMS = [
    Param("spokes", "int", 8, group="Spokes & Circles", min=1, max=90),
    Param("spoke_length", "float", 6.0, group="Spokes & Circles", min=0, max=24,
          help="Distance of each circle cluster from centre (cm)"),
    Param("spoke_rotation", "angle", 0.0, group="Spokes & Circles", min=0, max=180),
    Param("draw_spokes", "bool", True, group="Spokes & Circles"),
    Param("circles", "int", 20, group="Spokes & Circles", min=0, max=64),
    Param("circle_segments", "int", 90, group="Spokes & Circles", min=3, max=360),
    Param("circle_rotation", "angle", 0.0, group="Spokes & Circles", min=0, max=180),
    Param("circle_inner_rotation", "float", 0.0, group="Spokes & Circles", min=0, max=120),
    Param("random_circle_start", "bool", False, group="Spokes & Circles"),
    Param("outer_radius", "float", 3.6, group="Spokes & Circles", min=0.1, max=24,
          help="Radius of the outermost circle in each cluster (cm)"),
    Param("crop_radius", "float", 3.8, group="Spokes & Circles", min=0.1, max=24,
          help="Rays are erased inside this radius of each cluster (cm)"),
    Param("draw_crop_radius", "bool", False, group="Spokes & Circles"),
    Param("rays", "int", 128, group="Spokes & Circles", min=0, max=720),
    Param("ray_rotation", "angle", 0.0, group="Spokes & Circles", min=0, max=180),
    Param("seed", "int", 0, group="Spokes & Circles"),

    Param("pen_cycle", "bool", False, group="Pens",
          help="Distribute the drawing-set's pens across elements (off = single pen)"),
    Param("pen_spokes", "bool", True, group="Pens",
          help="Advance one pen per spoke"),
    Param("pen_circles", "enum", "per_cluster", group="Pens",
          choices=["off", "per_cluster", "per_ring"],
          help="off = first pen; per_cluster = one pen per spoke's circles; "
               "per_ring = a pen per ring (lined up across spokes)"),
    Param("pen_circle_stagger", "int", 0, group="Pens", min=0, max=32,
          help="Shift each successive circle cluster by this many pens in per-ring mode"),
    Param("pen_order", "enum", "forward", group="Pens", choices=["forward", "reverse"]),
    Param("pen_offset", "int", 0, group="Pens", min=0, max=32,
          help="Start the cycle at this pen"),
    Param("pen_rays", "int", 0, group="Pens", min=0, max=32,
          help="Pen number for the rays (0 = first pen; wraps past the list)"),
    Param("pen_border", "int", 0, group="Pens", min=0, max=32,
          help="Pen number for borders / margins / crop outlines (0 = first pen)"),
]

PAGE_PARAMS = [
    Param("page_width", "float", 29.7, group="Page", min=1, max=120, help="cm"),
    Param("page_height", "float", 42.0, group="Page", min=1, max=120, help="cm"),
    Param("side_margin", "float", 1.9, group="Page", min=0, max=20, help="cm"),
    Param("top_bottom_margin", "float", 3.0, group="Page", min=0, max=20, help="cm"),
    Param("draw_margin", "bool", False, group="Page"),
]

_SHAPE_FIELD_ALL_PARAMS = SHAPE_FIELD_PARAMS + PAGE_PARAMS + FRAMEWORK_PARAMS

GENERATORS = {
    "spokes_and_circles": {
        "id": "spokes_and_circles",
        "name": "Spokes & Circles",
        "params": _SPOKES_PARAMS + PAGE_PARAMS + FRAMEWORK_PARAMS,
        "fn": spokes_and_circles,
    },
    "shape_field": {
        "id": "shape_field",
        "name": "Shape Field",
        "editor": "shape_field",
        "params": _SHAPE_FIELD_ALL_PARAMS,
        "defaults": {"shape_layers": deepcopy(DEFAULT_SHAPE_LAYERS)},
        "shape_types": list(SHAPE_TYPES),
        "normalize": lambda values: normalize_shape_field_params(
            _SHAPE_FIELD_ALL_PARAMS, values
        ),
        "fn": shape_field,
    },
}


def list_generators() -> list[dict]:
    return [{"id": g["id"], "name": g["name"]} for g in GENERATORS.values()]


def get_generator(gid: str) -> dict:
    if gid not in GENERATORS:
        raise KeyError(f"Unknown generator {gid!r}")
    return GENERATORS[gid]
