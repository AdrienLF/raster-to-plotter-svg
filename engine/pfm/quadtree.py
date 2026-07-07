"""Quadtree Mosaic — recursively subdivide the image where local variance is
high, then render each leaf cell with a tone-matched component PFM.

Same crop/offset machinery as Mosaic Rectangles (`composite._mosaic_generate`),
but the partition follows image detail instead of a fixed grid: flat areas
stay as large calm cells, detailed areas split down to `min_cell_px`.
"""

from __future__ import annotations

import heapq

import numpy as np
from PIL import Image

from ..geometry import Geometry, Item
from ..image_ops import darkness, luminance
from ..params import Param
from .base import PFM, REGISTRY, generate_items, get, offset_items, register
from ._params import SEED

MAX_LEAVES = 1024
MIN_ALPHA_COVER = 0.05

# Component pool (composites excluded to avoid recursion; "none" leaves the
# cell empty — useful for light cells).
_POOL = ["none", "random_stipple", "grid_halftone", "hatch", "sketch_lines",
         "adaptive_shapes", "voronoi_stippling"]

# Density-matched overrides per component; d = mean darkness of the cell 0..1.
# Param names verified against each component's schema (see _TILE_OVERRIDES in
# composite.py for the same convention).
_DENSITY = {
    "random_stipple": lambda d: {"dot_count": int(100 + 900 * d)},
    "voronoi_stippling": lambda d: {"point_density": int(40 + 360 * d)},
    "grid_halftone": lambda d: {"grid_spacing": max(3.0, 9.0 - 6.0 * d)},
    "hatch": lambda d: {"line_spacing": max(4.0, 14.0 - 10.0 * d)},
    "adaptive_shapes": lambda d: {"max_sample_radius": max(4.0, 12.0 - 8.0 * d)},
    "sketch_lines": lambda d: {},
}


def _integrals(gray, alpha):
    """Summed-area tables for O(1) mean/variance/coverage over any rect."""
    def integral(a):
        s = np.zeros((a.shape[0] + 1, a.shape[1] + 1), dtype=np.float64)
        s[1:, 1:] = np.cumsum(np.cumsum(a, axis=0), axis=1)
        return s

    dmap = darkness(gray, alpha)
    return (integral(gray), integral(gray.astype(np.float64) ** 2),
            integral(dmap), integral(alpha))


def _rect_stats(tables, x0, y0, x1, y1):
    S1, S2, SD, SA = tables

    def box(S):
        return S[y1, x1] - S[y0, x1] - S[y1, x0] + S[y0, x0]

    area = max(1, (x1 - x0) * (y1 - y0))
    mean = box(S1) / area
    var = max(0.0, box(S2) / area - mean * mean)
    return var, box(SD) / area, box(SA) / area


def _quadtree_generate(work: Image.Image, v: dict, seed: int, bounds) -> list[Item]:
    W, H = work.size
    gray, alpha = luminance(work)
    tables = _integrals(gray, alpha)
    max_depth = int(v["max_depth"])
    min_cell = max(4, int(v["min_cell_px"]))
    thr = ((100.0 - float(v["detail"])) / 100.0) ** 2 * 0.05
    pad = float(v["padding"]) / 100.0

    # Best-first split by variance: when the leaf cap bites, the most detailed
    # cells keep subdividing and calm areas stay whole.
    counter = 0
    var0, _, _ = _rect_stats(tables, 0, 0, W, H)
    heap = [(-var0, counter, (0, 0, W, H), 0)]
    leaves: list[tuple[int, int, int, int]] = []
    while heap:
        negv, _, (x0, y0, x1, y1), depth = heapq.heappop(heap)
        can_split = (depth < max_depth and -negv > thr
                     and (x1 - x0) // 2 >= min_cell and (y1 - y0) // 2 >= min_cell
                     and len(leaves) + len(heap) + 3 <= MAX_LEAVES)
        if not can_split:
            leaves.append((x0, y0, x1, y1))
            continue
        mx, my = (x0 + x1) // 2, (y0 + y1) // 2
        for rect in ((x0, y0, mx, my), (mx, y0, x1, my),
                     (x0, my, mx, y1), (mx, my, x1, y1)):
            counter += 1
            var, _, _ = _rect_stats(tables, *rect)
            heapq.heappush(heap, (-var, counter, rect, depth + 1))

    items: list[Item] = []
    for (x0, y0, x1, y1) in leaves:
        _, mean_dark, cover = _rect_stats(tables, x0, y0, x1, y1)
        if cover < MIN_ALPHA_COVER:
            continue
        px = int((x1 - x0) * pad * 0.5)
        py = int((y1 - y0) * pad * 0.5)
        ix0, iy0, ix1, iy1 = x0 + px, y0 + py, x1 - px, y1 - py
        if ix1 - ix0 < 4 or iy1 - iy0 < 4:
            continue
        pid = v["style_dark"] if mean_dark >= 0.5 else v["style_light"]
        if pid != "none" and pid in REGISTRY:
            overrides = dict(_DENSITY.get(pid, lambda d: {})(mean_dark))
            sub = work.crop((ix0, iy0, ix1, iy1))
            cell_items = generate_items(get(pid), sub, overrides,
                                        seed + ix0 * 131 + iy0,
                                        (ix1 - ix0, iy1 - iy0))
            offset_items(cell_items, ix0, iy0)
            items.extend(cell_items)
        if bool(v["draw_outlines"]):
            rect_pts = [(ix0, iy0), (ix1, iy0), (ix1, iy1), (ix0, iy1)]
            items.append(Item(lum=float(mean_dark),
                              path=Geometry(rect_pts, closed=True)))
    return items


register(PFM(
    id="quadtree_mosaic", name="Quadtree Mosaic", family="composite", style="quadtree",
    params=SEED + [
        Param("max_depth", "int", 6, group="Subdivision", min=2, max=8,
              help="Maximum split depth (each level halves the cell)"),
        Param("min_cell_px", "int", 24, group="Subdivision", min=8, max=200,
              help="Never split below this cell size in working pixels"),
        Param("detail", "float", 60.0, group="Subdivision", min=0, max=100,
              help="How eagerly detailed areas subdivide (higher = more, smaller cells)"),
        Param("padding", "float", 6.0, group="Cells", min=0, max=60,
              help="Gap between cells, as a % of cell size"),
        Param("style_dark", "enum", "voronoi_stippling", group="Cells", choices=_POOL[1:],
              help="Component drawn in dark cells (density matched to tone)"),
        Param("style_light", "enum", "hatch", group="Cells", choices=_POOL,
              help="Component drawn in light cells (none = leave empty)"),
        Param("draw_outlines", "bool", False, group="Cells",
              help="Draw each cell's rectangle"),
    ],
    generate=_quadtree_generate,
))
