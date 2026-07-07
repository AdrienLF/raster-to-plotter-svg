"""Path Finding Module base + registry.

A PFM is a (sampler family x style) pairing plus a merged parameter schema.
``grid`` PFMs supply a custom ``generate`` callable instead of a sampler/style.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PIL import Image

from ..canvas import DrawingArea
from ..geometry import Drawing, clip_drawing
from ..params import Param, validate
from ..pens import DrawingSet, distribute
from ..sampling import SAMPLERS
from ..styles import STYLES

GenerateFn = Callable[[Image.Image, dict, int, tuple[int, int]], list]


@dataclass
class PFM:
    id: str
    name: str
    family: str                       # voronoi | lbg | adaptive | grid
    style: str                        # stippling | ... | (grid)
    params: list[Param]
    generate: GenerateFn | None = None  # for grid PFMs

    DRAFT_MAX_PX = 420   # longer side of the draft-preview working raster

    def run(self, image: Image.Image, area: DrawingArea, drawing_set: DrawingSet,
            values: dict, seed: int = 0, on_progress: Callable | None = None,
            paint_loader: Callable | None = None, draft: bool = False) -> Drawing:
        vals = validate(self.params, values)
        seed = int(vals.get("seed", seed) or 0)
        work = area.prepare_image(image, max_px=self.DRAFT_MAX_PX if draft else None)
        work = _apply_image_adjust(work, vals)
        from .. import fields
        vals["field_bindings"] = fields.normalize_bindings(
            (values or {}).get("field_bindings"), self.params)
        vals["_field_ctx"] = fields.FieldContext(work, seed, paint_loader)
        w, h = work.size
        if on_progress:
            on_progress("sampling", 0.1)

        if self.generate is not None:
            items = self.generate(work, vals, seed, (w, h))
        else:
            sites, weights = SAMPLERS[self.family].run(work, vals, seed)
            if on_progress:
                on_progress("styling", 0.6)
            items = STYLES[self.style](sites, weights, vals, (w, h))
        items = list(items)

        if on_progress:
            on_progress("distributing", 0.85)
        layers = distribute(items, drawing_set, seed)
        drawing = Drawing(width=w, height=h, area=area, layers=layers)
        if area.clipping == "drawing":
            clip_drawing(drawing, (0, 0, w, h))
        if on_progress:
            on_progress("done", 1.0)
        return drawing


def _apply_image_adjust(work: Image.Image, vals: dict) -> Image.Image:
    """Shared brightness/contrast, applied once to the working raster so every
    module (sampler-based or generate-based) speaks the same tonal language.
    Same math as image_ops.apply_brightness_contrast, per RGB channel."""
    b = float(vals.get("brightness", 1.0) or 1.0)
    c = float(vals.get("contrast", 1.0) or 1.0)
    if abs(b - 1.0) < 1e-6 and abs(c - 1.0) < 1e-6:
        return work
    import numpy as np
    mode = work.mode
    if mode not in ("RGB", "RGBA", "L", "LA"):
        work = work.convert("RGBA")
        mode = "RGBA"
    arr = np.asarray(work).astype(np.float32) / 255.0
    if mode in ("RGBA", "LA"):
        rgb, alpha = arr[..., :-1], arr[..., -1:]
    else:
        rgb, alpha = arr if arr.ndim == 3 else arr[..., None], None
    rgb = np.clip(((rgb - 0.5) * c + 0.5) * b, 0.0, 1.0)
    out = np.concatenate([rgb, alpha], axis=-1) if alpha is not None else rgb
    out = (out * 255.0 + 0.5).astype(np.uint8)
    if out.shape[-1] == 1:
        out = out[..., 0]
    return Image.fromarray(out, mode)


def generate_items(pfm: "PFM", work: Image.Image, values: dict, seed: int,
                   bounds: tuple[int, int],
                   paint_loader: Callable | None = None) -> list:
    """Run a PFM's generation stage on an already-prepared raster (no
    distribution/clipping). Used by Composite PFMs to invoke other modules."""
    vals = validate(pfm.params, values)
    from .. import fields
    vals["field_bindings"] = fields.normalize_bindings(
        (values or {}).get("field_bindings"), pfm.params)
    vals["_field_ctx"] = fields.FieldContext(work, seed, paint_loader)
    if pfm.generate is not None:
        return list(pfm.generate(work, vals, seed, bounds))
    sites, weights = SAMPLERS[pfm.family].run(work, vals, seed)
    return list(STYLES[pfm.style](sites, weights, vals, bounds))


def offset_items(items: list, dx: float, dy: float) -> list:
    """Translate every dot/path in a list of Items in place."""
    for it in items:
        if it.dot is not None:
            it.dot.x += dx
            it.dot.y += dy
        if it.path is not None:
            it.path.points = [(x + dx, y + dy) for x, y in it.path.points]
    return items


REGISTRY: dict[str, PFM] = {}


def register(pfm: PFM) -> PFM:
    from ._params import IMAGE_ADJUST
    names = {p.name for p in pfm.params}
    pfm.params = pfm.params + [p for p in IMAGE_ADJUST if p.name not in names]
    REGISTRY[pfm.id] = pfm
    return pfm


def get(pfm_id: str) -> PFM:
    if pfm_id not in REGISTRY:
        raise KeyError(f"Unknown PFM {pfm_id!r}")
    return REGISTRY[pfm_id]


def list_pfms() -> list[dict]:
    return [
        {"id": p.id, "name": p.name, "family": p.family, "style": p.style}
        for p in REGISTRY.values()
    ]
