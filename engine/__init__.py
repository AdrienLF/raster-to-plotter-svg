"""PlotterForge engine.

Pure-Python image -> geometry -> SVG pipeline. Knows nothing about Flask or
serial hardware. The web layer wraps this and feeds the generated SVG into the
existing plot worker.
"""

from .params import Param, validate, defaults, schema_json
from .geometry import Geometry, Dot, Layer, Drawing
from .canvas import DrawingArea, AREA_PRESETS
from . import pfm  # registers all path-finding modules

__all__ = [
    "Param",
    "validate",
    "defaults",
    "schema_json",
    "Geometry",
    "Dot",
    "Layer",
    "Drawing",
    "DrawingArea",
    "AREA_PRESETS",
    "pfm",
]
