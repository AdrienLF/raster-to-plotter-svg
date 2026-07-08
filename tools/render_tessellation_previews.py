"""Render deterministic picker previews for the built-in tessellation PFMs.

Writes web/static/pfm-previews/tessellation_*.png at the picker asset size
(440x621) from a fixed vertical tone gradient. Rasterizes with PIL directly
so no SVG toolchain is needed.

Run from the repo root: uv run python tools/render_tessellation_previews.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from engine.canvas import DrawingArea  # noqa: E402
from engine.pens import DrawingSet  # noqa: E402
from engine.pfm import REGISTRY  # noqa: E402
from engine.tessellation_patterns import BUILTIN_PATTERNS  # noqa: E402

SIZE = (440, 621)
OUT = ROOT / "web" / "static" / "pfm-previews"


def tone_gradient() -> Image.Image:
    img = Image.new("L", SIZE)
    for y in range(SIZE[1]):
        img.paste(int(20 + 215 * y / (SIZE[1] - 1)), (0, y, SIZE[0], y + 1))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    source = tone_gradient()
    for pfm_id in BUILTIN_PATTERNS:
        drawing = REGISTRY[pfm_id].run(source, DrawingArea(), DrawingSet(),
                                       {"columns": 10}, seed=0)
        sx = SIZE[0] / drawing.width
        sy = SIZE[1] / drawing.height
        canvas = Image.new("RGB", SIZE, "white")
        draw = ImageDraw.Draw(canvas)
        for layer in drawing.layers:
            for geo in layer.paths:
                points = [(x * sx, y * sy) for x, y in geo.points]
                if geo.closed:
                    points.append(points[0])
                if len(points) >= 2:
                    draw.line(points, fill="black", width=1)
        canvas.save(OUT / f"{pfm_id}.png")
        print(f"wrote {pfm_id}.png ({drawing.total()} items)")


if __name__ == "__main__":
    main()
