"""Grid family — ports of the original grid_halftone and random_stipple.

Kept for continuity (and as a fast, dependency-free baseline) now expressed as
PFMs producing distributable Items in working-pixel coordinates.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from ..geometry import Dot, Item
from ..image_ops import luminance
from ..params import Param
from .base import PFM, register
from ._params import SEED


def _grid_halftone(work: Image.Image, v: dict, seed: int, bounds) -> list[Item]:
    gray, alpha = luminance(work)
    h, w = gray.shape
    spacing = max(2, int(v["grid_spacing"]))
    min_r = float(v["min_radius"])
    max_r = float(v["max_radius"])
    items: list[Item] = []
    for row in range(0, h, spacing):
        for col in range(0, w, spacing):
            r2 = min(row + spacing, h)
            c2 = min(col + spacing, w)
            a = float(alpha[row:r2, col:c2].mean())
            if a < 0.15:
                continue
            t = (1.0 - float(gray[row:r2, col:c2].mean())) * a
            r = min_r + t * (max_r - min_r)
            if r <= 0:
                continue
            cx = col + (c2 - col) / 2.0
            cy = row + (r2 - row) / 2.0
            items.append(Item(lum=t, dot=Dot(cx, cy, r)))
    return items


def _random_stipple(work: Image.Image, v: dict, seed: int, bounds) -> list[Item]:
    gray, alpha = luminance(work)
    h, w = gray.shape
    prob = (1.0 - gray) * alpha
    total = prob.sum()
    if total == 0:
        return []
    flat = (prob / total).ravel()
    nonzero = int((flat > 0).sum())
    count = min(int(v["dot_count"]), nonzero)
    rng = np.random.default_rng(seed)
    idx = rng.choice(h * w, size=count, replace=False, p=flat)
    rows, cols = np.divmod(idx, w)
    radius = float(v["dot_radius"])
    jitter = float(v["jitter"])
    items: list[Item] = []
    for px, py in zip(cols.astype(float), rows.astype(float)):
        if jitter > 0:
            px += rng.uniform(-jitter, jitter)
            py += rng.uniform(-jitter, jitter)
        items.append(Item(lum=float(prob[int(py) % h, int(px) % w]), dot=Dot(px, py, radius)))
    return items


register(PFM(
    id="grid_halftone",
    name="Grid Halftone",
    family="grid",
    style="grid",
    params=SEED + [
        Param("grid_spacing", "int", 8, group="Grid", min=2, max=60,
              help="Size of each grid cell in pixels; smaller = more, finer dots"),
        Param("min_radius", "float", 0.3, group="Grid", min=0, max=15,
              help="Dot radius in the lightest cells"),
        Param("max_radius", "float", 3.0, group="Grid", min=0.5, max=20,
              help="Dot radius in the darkest cells"),
    ],
    generate=_grid_halftone,
))

register(PFM(
    id="random_stipple",
    name="Random Stipple",
    family="grid",
    style="grid",
    params=SEED + [
        Param("dot_count", "int", 8000, group="Grid", min=200, max=200_000,
              help="Total number of dots to place"),
        Param("dot_radius", "float", 1.5, group="Grid", min=0.3, max=15,
              help="Radius of every dot"),
        Param("jitter", "float", 0.0, group="Grid", min=0, max=10,
              help="Random offset added to each dot's position"),
    ],
    generate=_random_stipple,
))
