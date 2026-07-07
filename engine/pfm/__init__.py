"""PFM package — importing it registers every Path Finding Module."""

from __future__ import annotations

from .base import PFM, REGISTRY, get, list_pfms, register
from . import families  # noqa: F401  registers voronoi/lbg/adaptive x styles
from . import grid      # noqa: F401  registers grid halftone + random stipple
from . import spiral    # noqa: F401  registers spiral
from . import hatch     # noqa: F401  registers hatch
from . import sketch    # noqa: F401  registers sketch lines/curves/squares
from . import streamline  # noqa: F401  registers streamline flow/edge/superformula
from . import composite   # noqa: F401  registers layers + mosaic rectangles
from . import dither      # noqa: F401  registers Floyd-Steinberg dither halftone
from . import packing     # noqa: F401  registers circle packing
from . import growth      # noqa: F401  registers differential growth
from . import quadtree    # noqa: F401  registers quadtree mosaic

__all__ = ["PFM", "REGISTRY", "get", "list_pfms", "register"]
