"""Hatch family — parallel lines (optionally crosshatched) whose perpendicular
oscillation amplitude tracks darkness. Continuous single-pen output when
'Link Ends' is enabled.
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

_HATCH_PARAMS = [
    Param("line_spacing", "float", 6.0, group="Hatching", min=2, max=50,
          help="Distance between parallel lines"),
    Param("angle", "angle", 45.0, group="Hatching", min=-360, max=360,
          help="Direction of the hatching lines"),
    Param("crosshatch", "bool", False, group="Hatching",
          help="Draw a second pass of lines perpendicular to the first"),
    Param("link_ends", "bool", True, group="Hatching",
          help="Join line ends into one continuous path (fewer pen lifts)"),
    Param("wave_type", "enum", "sawtooth", group="Hatching",
          choices=["sawtooth", "sine", "none"],
          help="Shape of each line's wobble (none = straight lines that skip light areas instead)"),
    Param("amplitude", "float", 0.9, group="Hatching", min=0.01, max=2.0,
          help="How far each line swings side-to-side in the darkest areas"),
    Param("variable_velocity", "bool", True, group="Hatching",
          help="Wobble faster in light areas and slower in dark areas, instead of a fixed rate"),
    Param("min_velocity", "float", 5.0, group="Hatching", min=1, max=360,
          help="Wobble speed in the darkest areas (the fixed speed when Variable Velocity is off)"),
    Param("max_velocity", "float", 28.0, group="Hatching", min=1, max=360,
          help="Wobble speed in the lightest areas (ignored when Variable Velocity is off)"),
    Param("threshold", "float", 4.0, group="Hatching", min=0, max=100,
          help="Darkness % below which no line is drawn"),
]


def _hatch_set(d: np.ndarray, angle_deg: float, v: dict) -> list[Geometry]:
    h, w = d.shape
    spacing = max(2.0, float(v["line_spacing"]))
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    cx, cy = w / 2.0, h / 2.0
    diag = math.hypot(w, h)
    wave_type = v["wave_type"]
    amp_scale = float(v["amplitude"])
    var_vel = bool(v["variable_velocity"])
    min_vel = float(v["min_velocity"])
    max_vel = float(v["max_velocity"])
    thr = float(v["threshold"]) / 100.0
    step = 1.5

    lines: list[Geometry] = []
    vv = -diag / 2.0
    row = 0
    while vv <= diag / 2.0:
        phase = 0.0
        seg: list[tuple[float, float]] = []
        forward = row % 2 == 0
        u = -diag / 2.0 if forward else diag / 2.0
        uend = diag / 2.0 if forward else -diag / 2.0
        ustep = step if forward else -step
        while (u <= uend) if forward else (u >= uend):
            x = cx + u * ca - vv * sa
            y = cy + u * sa + vv * ca
            u += ustep
            if x < 0 or x >= w or y < 0 or y >= h:
                if len(seg) >= 2:
                    lines.append(Geometry(seg))
                seg = []
                continue
            dk = float(d[int(y), int(x)])
            if wave_type == "none":
                if dk < thr:
                    if len(seg) >= 2:
                        lines.append(Geometry(seg))
                    seg = []
                    continue
                seg.append((x, y))
            else:
                amp = spacing * 0.5 * amp_scale * dk
                wave = (
                    (2.0 / math.pi) * math.asin(math.sin(phase))
                    if wave_type == "sawtooth"
                    else math.sin(phase)
                )
                offset = amp * wave
                seg.append((x + (-sa) * offset, y + ca * offset))
                vel = (max_vel - dk * (max_vel - min_vel)) if var_vel else min_vel
                phase += (2 * math.pi) * step / max(vel, 1.0)
        if len(seg) >= 2:
            lines.append(Geometry(seg))
        vv += spacing
        row += 1
    return lines


def _hatch_generate(work: Image.Image, v: dict, seed: int, bounds) -> list[Item]:
    gray, alpha = luminance(work)
    d = darkness(gray, alpha)

    lines = _hatch_set(d, float(v["angle"]), v)
    if bool(v["crosshatch"]):
        lines += _hatch_set(d, float(v["angle"]) + 90.0, v)

    if not lines:
        return []

    if bool(v["link_ends"]) and v["wave_type"] != "none":
        joined: list[tuple[float, float]] = []
        for g in lines:
            joined.extend(g.points)
        return [Item(lum=0.5, path=Geometry(joined))]

    return [Item(lum=0.5, path=g) for g in lines]


register(PFM(
    id="hatch",
    name="Hatch",
    family="hatch",
    style="hatch",
    params=SEED + _HATCH_PARAMS,
    generate=_hatch_generate,
))
