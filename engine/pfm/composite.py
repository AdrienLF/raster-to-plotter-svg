"""Composite family — combine multiple PFMs.

- Layers: run several modules over the whole image and stack their output.
- Mosaic Rectangles: split the image into tiles, each rendered by a randomly
  chosen module and translated into place.

Both reuse `generate_items` so any registered (non-composite) module can be a
component. To keep the flat parameter schema usable, components run with their
default settings; pick the component via enum params.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from ..geometry import Geometry, Item
from ..image_ops import darkness, luminance
from ..params import Param
from .base import PFM, REGISTRY, generate_items, get, offset_items, register
from ._params import SEED

# Curated component pools (composite PFMs excluded to avoid recursion).
_LAYER_POOL = ["none", "random_stipple", "grid_halftone", "hatch", "sketch_lines",
               "adaptive_stippling", "adaptive_shapes", "voronoi_stippling",
               "spiral", "streamlines_flow_field"]
_TILE_POOL = ["random_stipple", "grid_halftone", "hatch", "sketch_lines",
              "adaptive_shapes", "voronoi_stippling"]

# Lighter per-component settings so a tiled mosaic stays plottable by default.
_TILE_OVERRIDES = {
    "random_stipple": {"dot_count": 500},
    "voronoi_stippling": {"point_density": 150},
    "grid_halftone": {"grid_spacing": 5},
    "adaptive_shapes": {"max_sample_radius": 9},
}


def _layers_generate(work: Image.Image, v: dict, seed: int, bounds) -> list[Item]:
    items: list[Item] = []
    for i, key in enumerate(("layer_1", "layer_2", "layer_3")):
        pid = v.get(key, "none")
        if pid == "none" or pid not in REGISTRY:
            continue
        items.extend(generate_items(get(pid), work, {}, seed + i * 17, bounds))
    return items


def _mosaic_generate(work: Image.Image, v: dict, seed: int, bounds) -> list[Item]:
    W, H = work.size
    cols = max(1, int(v["columns"]))
    rows = max(1, int(v["rows"]))
    pad = float(v["padding"]) / 100.0
    style_a = v["style_a"]
    style_b = v["style_b"]
    draw_outlines = bool(v["draw_outlines"])
    rng = np.random.default_rng(seed)

    gray, alpha = luminance(work)
    dmap = darkness(gray, alpha)

    tile_w = W / cols
    tile_h = H / rows
    items: list[Item] = []
    for r in range(rows):
        for c in range(cols):
            x0 = c * tile_w
            y0 = r * tile_h
            px = tile_w * pad * 0.5
            py = tile_h * pad * 0.5
            ix0, iy0 = int(x0 + px), int(y0 + py)
            ix1, iy1 = int(x0 + tile_w - px), int(y0 + tile_h - py)
            if ix1 - ix0 < 4 or iy1 - iy0 < 4:
                continue
            pid = style_a if rng.random() < 0.5 else style_b
            if pid not in REGISTRY:
                continue
            sub = work.crop((ix0, iy0, ix1, iy1))
            tile_items = generate_items(get(pid), sub, _TILE_OVERRIDES.get(pid, {}),
                                        seed + r * 131 + c, (ix1 - ix0, iy1 - iy0))
            offset_items(tile_items, ix0, iy0)
            items.extend(tile_items)
            if draw_outlines:
                lum = float(dmap[int(y0 + tile_h / 2) % H, int(x0 + tile_w / 2) % W])
                rect = [(ix0, iy0), (ix1, iy0), (ix1, iy1), (ix0, iy1)]
                items.append(Item(lum=lum, path=Geometry(rect, closed=True)))
    return items


register(PFM(
    id="layers", name="Layers", family="composite", style="layers",
    params=SEED + [
        Param("layer_1", "enum", "random_stipple", group="Layers", choices=_LAYER_POOL,
              help="PFM to run as one layer over the whole image (none = skip)"),
        Param("layer_2", "enum", "hatch", group="Layers", choices=_LAYER_POOL,
              help="PFM to run as one layer over the whole image (none = skip)"),
        Param("layer_3", "enum", "none", group="Layers", choices=_LAYER_POOL,
              help="PFM to run as one layer over the whole image (none = skip)"),
    ],
    generate=_layers_generate,
))

register(PFM(
    id="mosaic_rectangles", name="Mosaic Rectangles", family="composite", style="mosaic",
    params=SEED + [
        Param("columns", "int", 8, group="Tiles", min=1, max=64,
              help="Number of tile columns across the image"),
        Param("rows", "int", 8, group="Tiles", min=1, max=64,
              help="Number of tile rows down the image"),
        Param("padding", "float", 8.0, group="Tiles", min=0, max=100,
              help="Gap left between tiles, as a % of tile size"),
        Param("style_a", "enum", "random_stipple", group="Tiles", choices=_TILE_POOL,
              help="One of two PFMs randomly chosen for each tile"),
        Param("style_b", "enum", "hatch", group="Tiles", choices=_TILE_POOL,
              help="The other PFM randomly chosen for each tile"),
        Param("draw_outlines", "bool", False, group="Tiles",
              help="Draw a rectangle around each tile's border"),
    ],
    generate=_mosaic_generate,
))
