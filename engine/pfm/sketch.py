"""Sketch family — multi-pen tonal line drawings (the DrawingBotV3 signature).

Sketch Lines / Curves / Squares share one engine (engine.sketch.run_sketch) and
differ only in candidate directions and geometry conversion.
"""

from __future__ import annotations

from PIL import Image

from ..params import Param
from ..sketch import run_sketch
from .base import PFM, register
from ._params import SEED

_SKETCH_PARAMS = [
    Param("plotting_resolution", "float", 0.5, group="Sketch", min=0.1, max=1.5,
          help="Working-image scale; lower = faster, coarser"),
    Param("line_density", "float", 50.0, group="Segments", min=0, max=100,
          help="How much of the image's ink to lay down (drives when it stops)"),
    Param("line_min_length", "int", 6, group="Segments", min=2, max=500,
          help="Shortest a single segment can be"),
    Param("line_max_length", "int", 30, group="Segments", min=2, max=500,
          help="Longest a single segment can be"),
    Param("line_max_limit", "int", -1, group="Segments", min=-1, max=1_000_000,
          help="Hard cap on total segments (-1 = no limit)"),
    Param("angle_tests", "int", 24, group="Segments", min=1, max=360,
          help="Candidate directions checked at each step; more = smoother line-following, slower"),
    Param("drawing_delta_angle", "angle", 360.0, group="Style", min=-360, max=360,
          help="How far the next segment may turn from the previous one (360 = any direction)"),
    Param("directionality", "float", 0.0, group="Style", min=0, max=100,
          help="Bias toward continuing straight instead of always chasing the darkest direction"),
    Param("squiggle_min_length", "int", 0, group="Squiggles", min=0, max=5000,
          help="Minimum segments before a squiggle is allowed to end"),
    Param("squiggle_max_length", "int", 300, group="Squiggles", min=0, max=5000,
          help="Maximum segments in one continuous squiggle before lifting the pen"),
    Param("squiggle_max_deviation", "float", 25.0, group="Squiggles", min=0, max=100,
          help="How much lighter the path can get before the squiggle is allowed to end early"),
    Param("erase_max", "int", 130, group="Erasing", min=0, max=255,
          help="Ink removed per segment drawn; higher clears an area in fewer passes"),
]


def _make(mode: str):
    def gen(work: Image.Image, v: dict, seed: int, bounds):
        return run_sketch(work, v, seed, mode)
    return gen


register(PFM(
    id="sketch_lines", name="Sketch Lines", family="sketch", style="lines",
    params=SEED + _SKETCH_PARAMS, generate=_make("lines"),
))

register(PFM(
    id="sketch_curves", name="Sketch Curves", family="sketch", style="curves",
    params=SEED + _SKETCH_PARAMS + [
        Param("curve_tension", "float", 0.5, group="Curves", min=0.01, max=1.0,
              help="How tightly curves hug the original squiggle points (lower = looser, smoother curves)"),
    ],
    generate=_make("curves"),
))

register(PFM(
    id="sketch_squares", name="Sketch Squares", family="sketch", style="squares",
    params=SEED + _SKETCH_PARAMS + [
        Param("start_angle", "angle", 0.0, group="Squares", min=-360, max=360,
              help="Rotate the grid of candidate directions"),
    ],
    generate=_make("squares"),
))
