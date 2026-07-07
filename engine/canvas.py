"""Drawing Area.

Owns the output geometry: page size, orientation, padding, how the source image
is fitted, and — most importantly — derives the *working raster resolution* from
the drawing size and pen width. Sampling the image at "one pixel per pen stroke"
is what makes a plot come out at the correct density.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageOps

# Unit -> millimetres
_UNIT_MM = {"mm": 1.0, "cm": 10.0, "in": 25.4, "px": 25.4 / 96.0}

# Preset page sizes in mm (portrait W x H)
AREA_PRESETS: dict[str, tuple[float, float]] = {
    "A2": (420.0, 594.0),
    "A3": (297.0, 420.0),
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "A6": (105.0, 148.0),
    "Letter": (215.9, 279.4),
    "Square 200": (200.0, 200.0),
}

SCALING_MODES = ("crop", "scale", "stretch")
CLIPPING_MODES = ("drawing", "page", "none")
RESCALE_MODES = ("high", "low", "off")


@dataclass
class DrawingArea:
    use_original_sizing: bool = False
    units: str = "mm"
    width: float = 297.0             # in `units`
    height: float = 420.0            # in `units`
    orientation: str = "portrait"    # portrait | landscape
    pad_left: float = 0.0
    pad_right: float = 0.0
    pad_top: float = 0.0
    pad_bottom: float = 0.0
    scaling_mode: str = "crop"
    rescale_to_pen_width: bool = True
    rescale_mode: str = "high"
    pen_width_mm: float = 0.5
    canvas_colour: str = "#ffffff"
    background_colour: str = "#202020"
    clipping: str = "drawing"

    # ── unit helpers ───────────────────────────────────────────────────────────
    def _f(self) -> float:
        return _UNIT_MM.get(self.units, 1.0)

    def page_size_mm(self) -> tuple[float, float]:
        w = self.width * self._f()
        h = self.height * self._f()
        if self.orientation == "landscape" and h > w:
            w, h = h, w
        elif self.orientation == "portrait" and w > h:
            w, h = h, w
        return w, h

    def padding_mm(self) -> tuple[float, float, float, float]:
        f = self._f()
        return self.pad_left * f, self.pad_top * f, self.pad_right * f, self.pad_bottom * f

    def inner_rect_mm(self) -> tuple[float, float, float, float]:
        """(x, y, w, h) of the drawable region inside the padding, in mm."""
        pw, ph = self.page_size_mm()
        l, t, r, b = self.padding_mm()
        return l, t, max(1.0, pw - l - r), max(1.0, ph - t - b)

    # ── working raster ──────────────────────────────────────────────────────────
    def working_resolution(self, src_w: int, src_h: int,
                           max_px: int | None = None) -> tuple[int, int]:
        """Pixel dimensions of the raster the PFM should analyse.

        ``max_px`` caps the longer side (draft previews) without touching the
        aspect or the pen-width-derived proportions.
        """
        if self.use_original_sizing or not self.rescale_to_pen_width or self.rescale_mode == "off":
            # Match the source, but keep the inner aspect ratio.
            _, _, iw, ih = self.inner_rect_mm()
            aspect = iw / ih
            if src_w / max(1, src_h) > aspect:
                return src_w, max(1, int(round(src_w / aspect)))
            return max(1, int(round(src_h * aspect))), src_h
        _, _, iw_mm, ih_mm = self.inner_rect_mm()
        pen = max(0.05, self.pen_width_mm)
        w = max(8, int(round(iw_mm / pen)))
        h = max(8, int(round(ih_mm / pen)))
        if self.rescale_mode == "low":
            # Cap the working size to keep processing fast.
            cap = 1200
            scale = min(1.0, cap / max(w, h))
            w = max(8, int(round(w * scale)))
            h = max(8, int(round(h * scale)))
        if max_px:
            scale = min(1.0, max_px / max(w, h))
            w = max(8, int(round(w * scale)))
            h = max(8, int(round(h * scale)))
        return w, h

    def prepare_image(self, src: Image.Image, max_px: int | None = None) -> Image.Image:
        """Fit the source image into the working raster per the scaling mode."""
        w, h = self.working_resolution(src.width, src.height, max_px=max_px)
        if src.mode not in ("RGB", "RGBA", "L", "LA"):
            src = src.convert("RGBA")
        if self.scaling_mode == "stretch":
            return src.resize((w, h), Image.LANCZOS)
        if self.scaling_mode == "scale":
            fitted = ImageOps.contain(src, (w, h), Image.LANCZOS)
            canvas = Image.new("RGB", (w, h), self.canvas_colour)
            ox = (w - fitted.width) // 2
            oy = (h - fitted.height) // 2
            canvas.paste(fitted, (ox, oy))
            return canvas
        # default: crop to fill
        return ImageOps.fit(src, (w, h), Image.LANCZOS)

    # ── coordinate transform (working px -> page mm) ─────────────────────────────
    def px_to_mm(self, work_w: int, work_h: int):
        """Return a function mapping working-pixel (x,y) -> page-mm (x,y).

        The working raster fills the inner rect, so the scale is uniform.
        """
        ix, iy, iw, ih = self.inner_rect_mm()
        sx = iw / work_w
        sy = ih / work_h

        def f(x: float, y: float) -> tuple[float, float]:
            return ix + x * sx, iy + y * sy

        return f, (sx + sy) / 2.0

    def to_dict(self) -> dict:
        return {
            "use_original_sizing": self.use_original_sizing,
            "units": self.units,
            "width": self.width,
            "height": self.height,
            "orientation": self.orientation,
            "pad_left": self.pad_left,
            "pad_right": self.pad_right,
            "pad_top": self.pad_top,
            "pad_bottom": self.pad_bottom,
            "scaling_mode": self.scaling_mode,
            "rescale_to_pen_width": self.rescale_to_pen_width,
            "rescale_mode": self.rescale_mode,
            "pen_width_mm": self.pen_width_mm,
            "canvas_colour": self.canvas_colour,
            "background_colour": self.background_colour,
            "clipping": self.clipping,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "DrawingArea":
        d = d or {}
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)
