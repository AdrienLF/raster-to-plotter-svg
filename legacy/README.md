# Legacy desktop GUI

The original PlotterForge prototype: a small customtkinter desktop app that
converts one raster image into stippled dots and exports an SVG. It predates
the web app and is kept for reference only — everything it does is superseded
by the PlotterForge studio (`engine/` + `frontend/` + `web/`).

Run it with:

```sh
uv run python legacy/main.py
```

| File | Purpose | Superseded by |
|---|---|---|
| `main.py` | customtkinter GUI (load image → preview → export SVG) | the web app |
| `stipple.py` | `grid_halftone()` / `random_stipple()` | `engine/pfm/grid.py` |
| `svg_export.py` | `export_svg()` | `engine/svg_io.py` |
| `plotter.py` | direct Grbl serial driver for the iDraw H A3 | `web/server.py` plot worker |

## Usage

1. **Load image** — PNG, JPG, BMP, TIFF, WebP. Images with an alpha channel are
   supported; transparent pixels are skipped.
2. **Choose an algorithm** and tune its parameters (see below).
3. **Set physical width (mm)** to match the paper you'll plot on. Height is
   derived from the image aspect ratio.
4. Press **▶ Preview** to compute and render the dots.
5. Press **Export SVG…** to save.

## Algorithms

### Grid halftone

Dots are placed on a regular grid. Each cell's average brightness determines the
dot radius — dark cells get large dots, bright cells get small ones.

| Parameter | Description |
|---|---|
| Grid spacing (px) | Distance between dot centres. Smaller = finer detail, more dots. |
| Min dot radius (px) | Radius used for the lightest cells. Set to 0 to leave bright areas empty. |
| Max dot radius (px) | Radius used for the darkest cells. Should stay below half the grid spacing to avoid overlap. |

### Random stipple

Dots are scattered randomly across the image. Darker areas attract
proportionally more dots. All dots share the same radius, matching a fixed
pen-tip diameter.

| Parameter | Description |
|---|---|
| Dot count | Total number of dots to place. More dots = denser, finer result. |
| Dot radius (px) | Radius of every dot. Set this to match your pen tip (see below). |
| Position jitter (px) | Random offset added to each dot's position. Breaks up the pixel-grid look at high dot counts. |

### Matching dot radius to pen size

The SVG is output in millimetres. To size dots so they just touch without
overlapping, set dot radius to half your pen tip width in the units of the
source image:

```
dot_radius_px = (pen_tip_mm / output_width_mm) * image_width_px / 2
```

## SVG output

The exported file uses `mm` units and a `viewBox` matching the requested
physical dimensions. Every dot is a `<circle>` element with `fill="black"`.
