"""Circle packing — greedy, growth-limited-by-neighbours packing where each
circle's radius is bounded by local darkness (dark = big, light = small) *and*
by however much room its neighbours already claimed. Unlike the stippling
styles (fixed or lightly-varying dot size, positions carry the tone), here a
handful of large circles in dark regions and many tiny ones in light regions
carry it — the classic 'circle packing' generative-art look.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

from ..geometry import Dot, Item
from ..image_ops import luminance
from ..params import Param
from .base import PFM, register
from ._params import SEED

_PACKING_PARAMS = [
    Param("min_radius", "float", 1.0, group="Circle Packing", min=0.3, max=30,
          help="Smallest circle radius allowed"),
    Param("max_radius", "float", 8.0, group="Circle Packing", min=0.5, max=80,
          help="Largest circle radius, used in the darkest, most open areas"),
    Param("attempts", "int", 8000, group="Circle Packing", min=100, max=200_000,
          help="Random placement attempts (more = denser packing, slower)"),
    Param("ignore_white", "bool", True, group="Circle Packing",
          help="Skip placing circles on near-white background"),
]


def _circle_packing_generate(work: Image.Image, v: dict, seed: int, bounds) -> list[Item]:
    gray, alpha = luminance(work)
    h, w = gray.shape
    d = (1.0 - gray) * alpha

    min_r = max(0.3, float(v["min_radius"]))
    max_r = max(min_r + 0.1, float(v["max_radius"]))
    attempts = int(v["attempts"])
    ignore_white = bool(v.get("ignore_white", True))
    rng = np.random.default_rng(seed)

    if ignore_white:
        ys, xs = np.nonzero(d > 0.02)
        prob = d[ys, xs]
        prob = prob / prob.sum() if prob.size else prob
    else:
        yy, xx = np.mgrid[0:h, 0:w]
        ys, xs = yy.ravel(), xx.ravel()
        prob = None
    if ys.size == 0:
        return []

    # Draw every candidate pixel + jitter in one batched call: rng.choice(p=...)
    # rebuilds the cumulative distribution from scratch each call, so calling it
    # once per attempt inside the loop below would be O(attempts * pixels).
    idxs = rng.choice(xs.shape[0], size=attempts, p=prob) if prob is not None \
        else rng.integers(0, xs.shape[0], size=attempts)
    cand_x = xs[idxs].astype(np.float64) + rng.uniform(-0.5, 0.5, size=attempts)
    cand_y = ys[idxs].astype(np.float64) + rng.uniform(-0.5, 0.5, size=attempts)

    cell = max(1.0, max_r)
    grid: dict[tuple[int, int], list[int]] = {}
    cxs: list[float] = []
    cys: list[float] = []
    crs: list[float] = []
    reach = 2  # cell == max_r, so +-2 cells covers the max 2*max_r touch distance

    def gkey(x: float, y: float) -> tuple[int, int]:
        return int(x / cell), int(y / cell)

    for cx, cy in zip(cand_x.tolist(), cand_y.tolist()):
        if not (0 <= cx < w and 0 <= cy < h):
            continue
        local_d = float(d[int(cy), int(cx)])
        if ignore_white and local_d < 0.02:
            continue
        r_bound = min(min_r + local_d * (max_r - min_r), cx, cy, w - cx, h - cy)
        if r_bound < min_r:
            continue

        gx, gy = gkey(cx, cy)
        for ny in range(gy - reach, gy + reach + 1):
            for nx in range(gx - reach, gx + reach + 1):
                for idx in grid.get((nx, ny), ()):
                    dist = math.hypot(cx - cxs[idx], cy - cys[idx]) - crs[idx]
                    if dist < r_bound:
                        r_bound = dist
        if r_bound < min_r:
            continue

        idx = len(cxs)
        cxs.append(cx)
        cys.append(cy)
        crs.append(r_bound)
        grid.setdefault(gkey(cx, cy), []).append(idx)

    items: list[Item] = []
    for x, y, r in zip(cxs, cys, crs):
        lum = float(d[min(int(y), h - 1), min(int(x), w - 1)])
        items.append(Item(lum=lum, dot=Dot(x, y, r)))
    return items


register(PFM(
    id="circle_packing",
    name="Circle Packing",
    family="packing",
    style="packing",
    params=SEED + _PACKING_PARAMS,
    generate=_circle_packing_generate,
))
