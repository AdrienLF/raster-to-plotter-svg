"""Shape Dither: raster tone drives a grid of stamped shapes.

The image is downsampled to a coarse cell grid, each cell's tone is quantized
to N states from highlight to shadow (optionally with Floyd-Steinberg error
diffusion), and a shape is stamped per cell -- scaled between ``min_scale``
and ``max_scale`` by its state, optionally rotated to the local gradient
direction snapped to 90 degrees. The builtin module stamps the classic
primitive shapes; every custom shape in the ShapeLibrary (uploaded SVG or
Cavalry-baked multi-state artwork) registers as its own PFM, mirroring how
custom tessellation patterns work.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

from ..geometry import Geometry, Item
from ..image_ops import luminance
from ..params import Param
from ..shape_library import DitherShape
from ..styles import _SHAPE_TYPES, _shape_points
from ._params import SEED
from .base import PFM, register

MAX_CELLS = 50_000
MIN_ALPHA = 0.05

_GRID_PARAMS = [
    Param("aspect", "enum", "original", group="Grid",
          choices=["original", "square"],
          help="Sample the full image, or a centered 1:1 square crop of it"),
    Param("columns", "int", 40, group="Grid", min=4, max=160,
          help="Grid cells across the image (more = finer, smaller shapes)"),
]

_TONE_PARAMS = [
    Param("levels", "int", 5, group="Tone", min=2, max=32,
          help="Number of tone states from highlight to shadow"),
    Param("invert_tone", "bool", False, group="Tone",
          help="Swap which states dark and light areas of the source use"),
    Param("tone_response", "float", 1.0, group="Tone", min=0.1, max=5, step=0.05,
          help="Gamma applied to cell tone before picking a state (>1 favors light states)"),
    Param("dither_error", "bool", False, group="Tone",
          help="Diffuse quantization error to neighboring cells (Floyd-Steinberg)"),
]

_SHAPE_PARAMS = [
    Param("min_scale", "float", 0.10, group="Shape", min=0, max=1, step=0.01,
          help="Shape size in the lightest cells, as a fraction of the cell"),
    Param("max_scale", "float", 0.95, group="Shape", min=0.05, max=1.5, step=0.01,
          help="Shape size in the darkest cells (>1 overlaps neighboring cells)"),
    Param("rotate_with_image", "bool", False, group="Shape",
          help="Rotate each shape to the local image gradient, snapped to 90 degree steps"),
]

_COLOUR_PARAMS = [
    Param("shape_color", "color", "#000000", group="Colour",
          help="Colour used for the stamped shapes"),
    Param("background_enabled", "bool", False, group="Colour",
          help="Fill the page behind the shapes with the background colour (export only, never plotted)"),
    Param("background_color", "color", "#ffffff", group="Colour",
          help="Page background colour when enabled"),
]

_BUILTIN_SHAPE_PARAM = Param(
    "shape_type", "enum", "circle", group="Shape", choices=list(_SHAPE_TYPES),
    help="Primitive shape stamped in every cell")

_SOURCE_COLOURS_PARAM = Param(
    "use_source_colors", "bool", True, group="Colour",
    help="Keep the colours baked into the shape artwork instead of the shape colour")


# --------------------------------------------------------------------------
# Grid analysis
# --------------------------------------------------------------------------

def _cell_grids(work: Image.Image, v: dict):
    """Downsample the (optionally square-cropped) raster to per-cell darkness
    and coverage grids. Returns (darkness, coverage, x0, y0, cell, rows, cols)."""
    gray, alpha = luminance(work)
    h, w = gray.shape
    if str(v.get("aspect", "original")) == "square":
        side = min(w, h)
        x0, y0 = (w - side) // 2, (h - side) // 2
        rw = rh = side
    else:
        x0 = y0 = 0
        rw, rh = w, h

    cols = max(1, int(v["columns"]))
    cell = rw / cols
    rows = max(1, round(rh / cell))
    if rows * cols > MAX_CELLS:
        raise ValueError(f"Shape dither exceeds the {MAX_CELLS:,} cell limit; "
                         "reduce the grid resolution")

    darkness = (1.0 - gray) * alpha
    region_d = darkness[y0:y0 + rh, x0:x0 + rw].astype(np.float32)
    region_a = alpha[y0:y0 + rh, x0:x0 + rw].astype(np.float32)
    # BOX resize = true area averaging, handles fractional cell sizes.
    d = np.asarray(Image.fromarray(region_d, "F").resize((cols, rows), Image.BOX),
                   dtype=np.float64)
    a = np.asarray(Image.fromarray(region_a, "F").resize((cols, rows), Image.BOX),
                   dtype=np.float64)
    return d, a, x0, y0, cell, rows, cols


def _quantize(tone: np.ndarray, n: int, diffuse: bool) -> np.ndarray:
    """Per-cell state index in [0, n-1]; optionally with serpentine
    Floyd-Steinberg diffusion of the quantization error."""
    if not diffuse:
        return np.clip(np.rint(tone * (n - 1)), 0, n - 1).astype(int)
    q = tone.copy()
    k = np.zeros(tone.shape, dtype=int)
    rows, cols = tone.shape
    for row in range(rows):
        forward = row % 2 == 0
        step = 1 if forward else -1
        span = range(cols) if forward else range(cols - 1, -1, -1)
        for col in span:
            old = q[row, col]
            level = int(min(n - 1, max(0, round(old * (n - 1)))))
            k[row, col] = level
            err = old - level / (n - 1)
            nxt = col + step
            if 0 <= nxt < cols:
                q[row, nxt] += err * 7 / 16
            if row + 1 < rows:
                if 0 <= nxt < cols:
                    q[row + 1, nxt] += err * 1 / 16
                q[row + 1, col] += err * 5 / 16
                prv = col - step
                if 0 <= prv < cols:
                    q[row + 1, prv] += err * 3 / 16
    return k


def _snapped_rotations(darkness: np.ndarray) -> np.ndarray:
    """Local gradient direction per cell, snapped to the nearest 90 degrees.
    Cells with no meaningful gradient stay unrotated."""
    rows, cols = darkness.shape
    if rows < 2 or cols < 2:
        return np.zeros(darkness.shape)
    gy, gx = np.gradient(darkness)
    theta = np.arctan2(gy, gx)
    snapped = (np.rint(theta / (math.pi / 2)) % 4) * (math.pi / 2)
    snapped[np.hypot(gx, gy) < 1e-3] = 0.0
    return snapped


# --------------------------------------------------------------------------
# Stamping
# --------------------------------------------------------------------------

def _generate(work: Image.Image, v: dict, stamp) -> list[Item]:
    """Shared grid walk: tone analysis + per-cell ``stamp(cx, cy, size,
    rot, state_frac, lum) -> list[Geometry]``."""
    d, a, x0, y0, cell, rows, cols = _cell_grids(work, v)
    tone = 1.0 - d if bool(v.get("invert_tone")) else d
    tone = np.clip(tone, 0.0, 1.0) ** float(v.get("tone_response", 1.0))
    n = max(2, int(v["levels"]))
    k = _quantize(tone, n, bool(v.get("dither_error")))
    rot = (_snapped_rotations(d) if bool(v.get("rotate_with_image"))
           else np.zeros(d.shape))

    min_scale = float(v.get("min_scale", 0.1))
    max_scale = float(v.get("max_scale", 0.95))
    items: list[Item] = []
    for row in range(rows):
        for col in range(cols):
            if a[row, col] < MIN_ALPHA:
                continue
            state_frac = k[row, col] / (n - 1)
            frac = min_scale + state_frac * (max_scale - min_scale)
            if frac <= 1e-3:
                continue
            cx = x0 + (col + 0.5) * cell
            cy = y0 + (row + 0.5) * cell
            lum = float(d[row, col])
            for g in stamp(cx, cy, frac * cell, float(rot[row, col]),
                           state_frac, lum):
                items.append(Item(lum=lum, path=g))
    return items


def _builtin_generate(work: Image.Image, v: dict, seed: int, bounds) -> list[Item]:
    kind = str(v.get("shape_type", "circle"))
    colour = v.get("shape_color") or "#000000"

    def stamp(cx, cy, size, rot, state_frac, lum):
        pts = _shape_points(kind, cx, cy, size / 2.0, rot)
        return [Geometry(pts, closed=True, colour=colour, fill=colour)]

    return _generate(work, v, stamp)


def _shape_generate(shape: DitherShape, work: Image.Image, v: dict) -> list[Item]:
    use_source = bool(v.get("use_source_colors", True))
    colour = v.get("shape_color") or "#000000"
    n_states = len(shape.states)

    def stamp(cx, cy, size, rot, state_frac, lum):
        state = shape.states[round(state_frac * (n_states - 1))] if n_states > 1 \
            else shape.states[0]
        c, s = math.cos(rot), math.sin(rot)
        out = []
        for path in state.paths:
            pts = [(cx + (px * c - py * s) * size, cy + (px * s + py * c) * size)
                   for px, py in path.points]
            if use_source:
                stroke = path.stroke or ("none" if path.fill else None)
                fill = path.fill
            else:
                stroke = "none" if (path.fill and not path.stroke) else colour
                fill = colour if path.fill else None
            out.append(Geometry(pts, closed=path.closed, colour=stroke, fill=fill))
        return out

    return _generate(work, v, stamp)


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------

BUILTIN_PARAMS = (SEED + _GRID_PARAMS + _TONE_PARAMS
                  + _SHAPE_PARAMS + [_BUILTIN_SHAPE_PARAM] + _COLOUR_PARAMS)

CUSTOM_PARAMS = (SEED + _GRID_PARAMS + _TONE_PARAMS
                 + _SHAPE_PARAMS + [_SOURCE_COLOURS_PARAM] + _COLOUR_PARAMS)

register(PFM(
    id="shape_dither",
    name="Shape Dither",
    family="shape_dither",
    style="shape_dither",
    params=list(BUILTIN_PARAMS),
    generate=_builtin_generate,
))


def register_shape_pfm(shape: DitherShape) -> PFM:
    def generate(work, values, seed, bounds):
        return _shape_generate(shape, work, values)
    return register(PFM(id=shape.id, name=f"Shape Dither · {shape.name}",
                        family="shape_dither", style="shape_dither",
                        params=list(CUSTOM_PARAMS), generate=generate))


def replace_shape_pfm(shape: DitherShape) -> PFM:
    """Register or replace the PFM for a (re)installed custom shape.

    ``register()`` assigns ``REGISTRY[pfm.id]``, so re-registering the same
    stable ID swaps the shape in place without touching layers already
    rendered from the previous version."""
    return register_shape_pfm(shape)
