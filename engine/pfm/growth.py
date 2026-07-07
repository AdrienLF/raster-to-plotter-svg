"""Differential Growth PFM — self-avoiding organic curves seeded by tone."""

from __future__ import annotations

from ..growth import run_growth
from ..params import Param
from ._params import SEED
from .base import PFM, register

_GROWTH_PARAMS = [
    Param("seed_count", "int", 12, group="Growth", min=1, max=64,
          help="How many growth curves to start, placed in the darkest areas"),
    Param("seed_power", "float", 3.0, group="Growth", min=0.5, max=10,
          help="How strongly seeds favor dark areas"),
    Param("closed_loops", "bool", True, group="Growth",
          help="Grow closed blobs instead of open curves"),
    Param("iterations", "int", 250, group="Growth", min=20, max=800,
          help="Growth steps; more = denser, more folded"),
    Param("min_dist", "float", 2.5, group="Growth", min=1, max=10,
          help="Node spacing floor (px); smaller = finer folds, slower"),
    Param("max_dist", "float", 6.0, group="Growth", min=2, max=20,
          help="Edge length that triggers subdivision in light areas"),
    Param("repulsion_radius", "float", 8.0, group="Growth", min=2, max=30,
          help="How far apart strands push each other"),
    Param("k_align", "float", 0.45, group="Growth", min=0, max=1,
          help="Curve smoothing pull toward neighbors"),
    Param("k_rep", "float", 0.6, group="Growth", min=0, max=2,
          help="Self-avoidance push strength"),
    Param("k_dark", "float", 0.3, group="Growth", min=0, max=2,
          help="Pull toward darker image areas"),
    Param("jitter", "float", 0.3, group="Growth", min=0, max=2,
          help="Random wobble on new nodes (organic asymmetry)"),
]

register(PFM(
    id="differential_growth", name="Differential Growth",
    family="growth", style="growth",
    params=SEED + _GROWTH_PARAMS,
    generate=run_growth,
))
