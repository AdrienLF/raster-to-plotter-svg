"""Error-diffusion halftone — classic Floyd-Steinberg dithering (1976), read
as a stipple placement rule instead of a printed dot pattern: the image is
downsampled to a coarse cell grid, each cell is thresholded to on/off, and the
rounding error is diffused to not-yet-visited neighbours (serpentine scan
mirrors the kernel on alternating rows to avoid a directional drift artifact).
Deterministic given the image — the 'seed' param only affects jitter.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from ..geometry import Dot, Item
from ..image_ops import luminance
from ..params import Param
from .base import PFM, register
from ._params import SEED

_DITHER_PARAMS = [
    Param("cell_size", "int", 4, group="Dither", min=1, max=40,
          help="Image pixels per potential dot"),
    Param("dot_radius", "float", 2.0, group="Dither", min=0.2, max=20,
          help="Radius of each placed dot"),
    Param("bias", "float", 0.0, group="Dither", min=-50, max=50,
          help="Shift overall darkness before thresholding (+ = more dots)"),
    Param("serpentine", "bool", True, group="Dither",
          help="Alternate scan direction per row (avoids a diagonal streak artifact)"),
    Param("jitter", "float", 0.0, group="Dither", min=0, max=10,
          help="Random offset added to each placed dot"),
]


def _dither_generate(work: Image.Image, v: dict, seed: int, bounds) -> list[Item]:
    gray, alpha = luminance(work)
    h, w = gray.shape
    cell = max(1, int(v["cell_size"]))
    gh, gw = h // cell, w // cell
    if gh < 1 or gw < 1:
        return []

    hc, wc = gh * cell, gw * cell
    d = (1.0 - gray[:hc, :wc]) * alpha[:hc, :wc]
    d = d.reshape(gh, cell, gw, cell).mean(axis=(1, 3)).astype(np.float64)
    bias = float(v.get("bias", 0.0)) / 100.0
    if bias:
        d = np.clip(d + bias, 0.0, 1.0)

    serpentine = bool(v.get("serpentine", True))
    radius = float(v["dot_radius"])
    jitter = float(v.get("jitter", 0.0))
    rng = np.random.default_rng(seed)

    items: list[Item] = []
    for row in range(gh):
        forward = (not serpentine) or (row % 2 == 0)
        step = 1 if forward else -1
        cols = range(gw) if forward else range(gw - 1, -1, -1)
        for col in cols:
            old = d[row, col]
            on = old >= 0.5
            err = old - (1.0 if on else 0.0)
            if on:
                cx = col * cell + cell / 2.0
                cy = row * cell + cell / 2.0
                if jitter > 0:
                    cx += rng.uniform(-jitter, jitter)
                    cy += rng.uniform(-jitter, jitter)
                items.append(Item(lum=float(old), dot=Dot(cx, cy, radius)))
            nxt = col + step
            if 0 <= nxt < gw:
                d[row, nxt] += err * 7 / 16
            if row + 1 < gh:
                if 0 <= nxt < gw:
                    d[row + 1, nxt] += err * 1 / 16
                d[row + 1, col] += err * 5 / 16
                prv = col - step
                if 0 <= prv < gw:
                    d[row + 1, prv] += err * 3 / 16
    return items


register(PFM(
    id="dither_halftone",
    name="Dither Halftone",
    family="dither",
    style="dither",
    params=SEED + _DITHER_PARAMS,
    generate=_dither_generate,
))
