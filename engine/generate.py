"""Rule-based drawing generators (the "Generate" step).

Port of revdancatt-style pen-plotter generators. These take no input image —
they build geometry directly from parameters and output polylines in mm.

First generator: Spokes & Circles — a sunburst of rays plus rings of concentric
circles, with the rays culled out from inside each circle cluster.
"""

from __future__ import annotations

import math
import random

from .geometry import clip_polyline
from .params import Param

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


def _clip_lines_to_rect(lines: list[Line], rect: tuple[float, float, float, float]) -> list[Line]:
    out: list[Line] = []
    for line in lines:
        for sub in clip_polyline(line, rect):
            out.append(sub)
    return out


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


def cull_inside_circle(lines: list[Line], cx: float, cy: float, r: float) -> list[Line]:
    """Remove the parts of each line that fall inside the circle."""
    out: list[Line] = []
    for line in lines:
        for p0, p1 in zip(line, line[1:]):
            for a, b in _segment_outside_circle(p0, p1, cx, cy, r):
                out.append([a, b])
    return out


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

    pattern: list[Line] = []
    for s in range(spokes):
        sp_ang = angle * s + 90 + float(p["spoke_rotation"])

        if p["draw_spokes"]:
            spoke = [(0.0, 0.0), (0.0, -spoke_len)]
            spoke = translate(rotate(spoke, sp_ang), cx_pg, cy_pg)
            pattern.append(spoke)

        for c in range(1, circles + 1):
            circ = make_circle(cseg, circle_step * c)
            amount = (rng.randrange(cseg) * (360.0 / cseg)) if p["random_circle_start"] else 0.0
            circ = rotate(circ, float(p["circle_rotation"])
                          + (circles - c) * float(p["circle_inner_rotation"]) + amount + 90)
            circ = translate(circ, 0, -spoke_len)
            circ = translate(rotate(circ, sp_ang), cx_pg, cy_pg)
            pattern.append(circ)

        # cluster centre (where the cropping circle sits)
        ccx, ccy = translate(rotate([(0.0, -spoke_len)], sp_ang), cx_pg, cy_pg)[0]
        if p["draw_crop_radius"]:
            crop = make_circle(cseg, float(p["crop_radius"]))
            crop = rotate(crop, float(p["circle_rotation"]) + 90)
            crop = translate(crop, 0, -spoke_len)
            crop = translate(rotate(crop, sp_ang), cx_pg, cy_pg)
            pattern.append(crop)
        ray_lines = cull_inside_circle(ray_lines, ccx, ccy, float(p["crop_radius"]))

    pattern.extend(ray_lines)

    if p["draw_margin"]:
        x0, y0, x1, y1 = rect
        pattern.append([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])

    lines_mm = [[(x * 10.0, y * 10.0) for x, y in line] for line in pattern if len(line) >= 2]
    return lines_mm, pw * 10.0, ph * 10.0


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
]

_PAGE_PARAMS = [
    Param("page_width", "float", 29.7, group="Page", min=1, max=120, help="cm"),
    Param("page_height", "float", 42.0, group="Page", min=1, max=120, help="cm"),
    Param("side_margin", "float", 1.9, group="Page", min=0, max=20, help="cm"),
    Param("top_bottom_margin", "float", 3.0, group="Page", min=0, max=20, help="cm"),
    Param("draw_margin", "bool", False, group="Page"),
]

GENERATORS = {
    "spokes_and_circles": {
        "id": "spokes_and_circles",
        "name": "Spokes & Circles",
        "params": _SPOKES_PARAMS + _PAGE_PARAMS,
        "fn": spokes_and_circles,
    },
}


def list_generators() -> list[dict]:
    return [{"id": g["id"], "name": g["name"]} for g in GENERATORS.values()]


def get_generator(gid: str) -> dict:
    if gid not in GENERATORS:
        raise KeyError(f"Unknown generator {gid!r}")
    return GENERATORS[gid]
