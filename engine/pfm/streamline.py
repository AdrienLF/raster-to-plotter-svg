"""Streamline family — evenly-spaced streamlines through a vector field."""

from __future__ import annotations

from PIL import Image

from ..params import Param
from ..streamline import run_streamlines
from .base import PFM, register
from ._params import SEED

_STREAM_PARAMS = [
    Param("min_spacing", "float", 3.0, group="Streamlines", min=0.5, max=20,
          help="Closest streamlines get to each other, in working pixels (≈ pen widths), used in the darkest areas"),
    Param("max_spacing", "float", 10.0, group="Streamlines", min=2, max=50,
          help="Distance between streamlines in the lightest areas, in working pixels (≈ pen widths)"),
    Param("min_length", "float", 6.0, group="Streamlines", min=0, max=200,
          help="Discard streamlines shorter than this"),
    Param("max_length", "float", 200.0, group="Streamlines", min=0, max=500,
          help="Longest a single streamline can grow"),
    Param("tone", "float", 50.0, group="Streamlines", min=0, max=100,
          help="How strongly midtones are pulled toward the dark-area spacing (higher = more of the contrast is packed into the shadows)"),
    Param("distortion", "float", 0.0, group="Streamlines", min=0, max=100,
          help="Random wobble added to each streamline's direction as it's traced"),
    Param("spacing_scale", "float", 1.0, group="Streamlines", min=0.25, max=4.0,
          bindable=True,
          help="Per-pixel multiplier on line spacing; bind a field to vary density independently of tone"),
]

_FLOW_PARAMS = [
    Param("start_angle", "angle", 0.0, group="Flow Field", min=-360, max=360,
          help="Base direction of the flow field"),
    Param("x_freq", "float", 1.0, group="Flow Field", min=0.001, max=4,
          help="How rapidly the flow direction oscillates across the image, left-to-right"),
    Param("y_freq", "float", 1.0, group="Flow Field", min=0.001, max=4,
          help="How rapidly the flow direction oscillates across the image, top-to-bottom"),
    Param("scale_freq", "float", 1.0, group="Flow Field", min=0.01, max=20,
          help="Overall scale multiplier applied to both frequencies above"),
    Param("amplitude", "float", 0.5, group="Flow Field", min=0.0, max=1.0,
          help="How far the flow direction swings away from the base angle"),
]

_EDGE_PARAMS = [
    Param("edge_power", "float", 70.0, group="Edge Field", min=0, max=100,
          help="How strongly streamlines follow image edges vs. the flow field (100 = edges only)"),
    Param("etf_iterations", "int", 4, group="Edge Field", min=0, max=30,
          help="Smoothing passes over the detected edge directions; more = smoother, less noisy flow"),
]

_SUPER_PARAMS = [
    Param("start_angle", "angle", 0.0, group="Superformula", min=-360, max=360,
          help="Base rotation of the rosette pattern"),
    Param("centre_x", "float", 50.0, group="Superformula", min=0, max=100,
          help="Pattern center, as a % of image width"),
    Param("centre_y", "float", 50.0, group="Superformula", min=0, max=100,
          help="Pattern center, as a % of image height"),
    Param("frequency", "float", 6.0, group="Superformula", min=0.0, max=20,
          help="Number of lobes in the rosette pattern"),
]


def _make(kind: str):
    def gen(work: Image.Image, v: dict, seed: int, bounds):
        return run_streamlines(work, v, seed, kind)
    return gen


register(PFM(
    id="streamlines_flow_field", name="Streamlines Flow Field",
    family="streamline", style="flow",
    params=SEED + _STREAM_PARAMS + _FLOW_PARAMS, generate=_make("flow"),
))

register(PFM(
    id="streamlines_edge_field", name="Streamlines Edge Field",
    family="streamline", style="edge",
    params=SEED + _STREAM_PARAMS + _EDGE_PARAMS + _FLOW_PARAMS, generate=_make("edge"),
))

register(PFM(
    id="streamlines_superformula", name="Streamlines Superformula",
    family="streamline", style="superformula",
    params=SEED + _STREAM_PARAMS + _SUPER_PARAMS, generate=_make("superformula"),
))
