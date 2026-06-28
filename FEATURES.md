# Features

A running list of what this software does. One line each. Updated on every commit.

## Image input
- **Image upload** — Load PNG/JPG/BMP/TIFF/WebP; alpha respected (transparent pixels skipped). Shows a loading status while the file uploads.
- **Source image view** — Original image shown aspect-correct, centered in the page.

## Regions (segmentation)
- **AI segmentation** — Click-to-segment the source image into regions (`/api/segmentation/predict`).
- **SAM model picker** — Choose the SAM 2.1 variant (tiny/small/base_plus/large); auto-downloads the checkpoint, choice persisted in settings.
- **SAM setup feedback** — Model install/download runs in the background (non-blocking) with live status: "Installing…", "Downloading… N%", a ready indicator, and errors surfaced in the panel.
- **Region management** — Create, rename, delete, and select regions; each carries its own mask.
- **Region masks** — Per-region alpha mask applied to the source for isolated path finding.

## Path Finding Modules (PFMs)
- **~23 PFMs** — Voronoi / LBG / Adaptive samplers × Stippling, Dashes, Shapes, Triangulation, Tree, Diagram, TSP styles, plus Grid Halftone and Random Stipple.
- **Schema-driven params** — Every PFM's controls auto-generated from a typed schema (`engine/params.py`).
- **GPU acceleration** — Torch (MPS/CUDA) for nearest-site / weighted-centroid stages; numpy/scipy CPU fallback. Active backend shown in status bar.
- **Generators** — Procedural pattern generators distinct from image-driven PFMs (`/api/generate`).

## Composition (layers)
- **Layer stack** — Multiple stacked layers, each bound to a region or the whole image; reorder, duplicate, delete, toggle visibility.
- **Per-layer path finding** — Run a PFM per layer with independent params (`/pathfinding/generate`); switching a layer back to "Whole image" regenerates without the old region.
- **Display modes** — Show a layer as raster, pathfinding paths, or both.
- **Layer raster preview** — Served raster matches what the pathfinder analysed (aspect-correct, aligns with paths).
- **Transform** — Move and scale layers in the viewport with handles.
- **Crop & mask** — Rectangle crop and rect/pen masks per layer; crop-to-content.
- **Occlusion** — Upper layers knock out lower layers along their actual mask/region outline (traced polygon), not just a bounding box.

## Drawing area & pens
- **Drawing Area** — Page size, units, orientation, padding, scaling mode, pen-width rescaling.
- **Drawing Sets (pens)** — Multi-pen sets with colour/stroke width; items distributed across pens. Pen library presets.

## Viewport
- **Pan / zoom / fit** — Wheel zoom, drag pan, one-shot auto-fit, Fit button.
- **Snapping guides** — Alignment guides while moving layers.

## Versions
- **Snapshot version control** — Save, load, rename, reorder, delete drawing snapshots with thumbnails.

## Feedback & status
- **Status bar** — Shows backend (GPU/CPU), current operation, progress bar, and plot elapsed/remaining/shape counts.
- **Useful errors** — Failures show the actual message (e.g. "Layer pathfinding error: …") in red in the status bar, never a bare "Error"; full text on hover.

## Output & plotting
- **Multi-layer SVG export** — mm-unit SVG with a viewBox; one Inkscape layer group per pen.
- **Direct plotting** — Drive the plotter from the app: estimate, plot, pause/resume, discard, stop; live progress over SSE (`/api/stream`).
- **Manual jog** — Manual plotter movement commands (`/api/manual`).
- **Wireless plotting** — Drive the iDraw from Mac Inkscape over a Tailscale `socat` serial bridge (see `bridge/`).

## Projects
- **Project management** — Create, open, rename, delete projects; stored under `~/.plotter_studio/`.
- **Settings** — Persisted app settings (`/api/settings`).
