"""Spiral family — a single continuous spiral whose perpendicular amplitude
tracks image darkness. Suitable for single-pen plots with no pen lifts.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

from ..geometry import Geometry, Item
from ..image_ops import darkness, luminance
from ..params import Param
from .base import PFM, register
from ._params import SEED

_SPIRAL_PARAMS = [
    Param("spiral_type", "enum", "archimedean", group="Spiral",
          choices=["archimedean", "sawtooth"],
          help="Shape of the perpendicular wobble: archimedean = smooth sine wave, sawtooth = pointed zigzag"),
    Param("spiral_size", "float", 100.0, group="Spiral", min=1, max=100,
          help="How far the spiral grows (100 = reaches the corner)"),
    Param("centre_x", "float", 50.0, group="Spiral", min=0, max=100,
          help="Spiral center, as a % of image width"),
    Param("centre_y", "float", 50.0, group="Spiral", min=0, max=100,
          help="Spiral center, as a % of image height"),
    Param("ring_spacing", "float", 6.0, group="Spiral", min=1, max=50,
          help="Distance between spiral rings"),
    Param("amplitude", "float", 0.9, group="Spiral", min=0.01, max=2.0,
          help="How far the spiral swings side-to-side in the darkest areas"),
    Param("variable_velocity", "bool", True, group="Spiral",
          help="Wobble faster in light areas and slower in dark areas, instead of a fixed rate"),
    Param("min_velocity", "float", 6.0, group="Spiral", min=1, max=360,
          help="Wobble speed in the darkest areas (the fixed speed when Variable Velocity is off)"),
    Param("max_velocity", "float", 30.0, group="Spiral", min=1, max=360,
          help="Wobble speed in the lightest areas (ignored when Variable Velocity is off)"),
    Param("ignore_white", "bool", True, group="Spiral",
          help="Keep the spiral centered over near-white background instead of wobbling there"),
]


def _sample(d: np.ndarray, x: float, y: float) -> float:
    h, w = d.shape
    ix = min(max(int(x), 0), w - 1)
    iy = min(max(int(y), 0), h - 1)
    return float(d[iy, ix])


def _spiral_generate(work: Image.Image, v: dict, seed: int, bounds) -> list[Item]:
    gray, alpha = luminance(work)
    d = darkness(gray, alpha)
    h, w = d.shape

    cx = v["centre_x"] / 100.0 * w
    cy = v["centre_y"] / 100.0 * h
    ring = max(1.0, float(v["ring_spacing"]))
    amp_scale = float(v["amplitude"])
    sawtooth = v["spiral_type"] == "sawtooth"
    ignore_white = bool(v["ignore_white"])
    var_vel = bool(v["variable_velocity"])
    min_vel = float(v["min_velocity"])
    max_vel = float(v["max_velocity"])

    # furthest corner distance scaled by spiral_size
    far = max(
        math.hypot(cx, cy), math.hypot(w - cx, cy),
        math.hypot(cx, h - cy), math.hypot(w - cx, h - cy),
    )
    max_r = far * v["spiral_size"] / 100.0

    b = ring / (2 * math.pi)        # Archimedean: r = b * theta
    step_len = 1.5                  # arc step in px
    theta = ring / b                # start one ring out to avoid the singularity
    phase = 0.0
    pts: list[tuple[float, float]] = []
    dsum = 0.0
    n = 0

    while True:
        r = b * theta
        if r > max_r:
            break
        bx = cx + r * math.cos(theta)
        by = cy + r * math.sin(theta)
        # tangent / normal
        tx = math.cos(theta) - theta * math.sin(theta)
        ty = math.sin(theta) + theta * math.cos(theta)
        tl = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / tl, tx / tl

        dk = _sample(d, bx, by)
        dsum += dk
        n += 1

        amp = ring * 0.5 * amp_scale * dk
        if ignore_white and dk < 0.02:
            offset = 0.0
        else:
            wave = (2.0 / math.pi) * math.asin(math.sin(phase)) if sawtooth else math.sin(phase)
            offset = amp * wave
        pts.append((bx + nx * offset, by + ny * offset))

        # advance
        dtheta = step_len / max(r, 1e-3)
        theta += dtheta
        vel = (max_vel - dk * (max_vel - min_vel)) if var_vel else min_vel
        phase += (2 * math.pi) * step_len / max(vel, 1.0)

    if len(pts) < 2:
        return []
    lum = dsum / max(1, n)
    return [Item(lum=lum, path=Geometry(pts))]


register(PFM(
    id="spiral",
    name="Spiral",
    family="spiral",
    style="spiral",
    params=SEED + _SPIRAL_PARAMS,
    generate=_spiral_generate,
))
