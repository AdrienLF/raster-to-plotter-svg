# Features

A running list of what this software does. One line each. Updated on every commit.

## Image input
- **Image upload** — Load PNG/JPG/BMP/TIFF/WebP as a new raster composition layer; alpha is respected (transparent pixels are skipped) and loading status is shown while the file uploads.
- **Non-destructive image placement** — The complete image is fitted and centred inside the drawing area without cropping, then remains freely movable, scalable, and rotatable; Fit and Fill can reframe it at any time.
- **EXIF-correct photos** — Phone/camera orientation is baked into imported pixels so the layer box, browser preview, and path finding all use the photo's true aspect ratio.

## Regions (segmentation)
- **AI segmentation** — Click-to-segment the source image into regions (`/api/segmentation/predict`).
- **SAM model picker** — Choose the SAM 2.1 variant (tiny/small/base_plus/large); the checkpoint downloads on demand, choice persisted in settings.
- **SAM setup feedback** — SAM2 and the pinned PyTorch build are installed by the platform setup script (`setup-windows.bat` / `./setup-macos.command`), which verifies a real segmentation inference. The server never installs packages at runtime; if SAM2, Torch, or the checkpoint is missing it reports a setup-incomplete error pointing at the setup script. The checkpoint (a plain file) still downloads in the background with live status: "Downloading… N%".
- **Region management** — Create, rename, delete, and select regions; each carries its own mask.
- **Region masks** — Per-region alpha mask applied to the source for isolated path finding.

## Path Finding Modules (PFMs)
- **50 PFMs** — Voronoi / LBG / Adaptive / Poisson-disk samplers × Stippling, Dashes, Shapes, Triangulation, Tree, Diagram, TSP styles, plus Grid Halftone, Random Stipple, Spiral, Hatch, Sketch (Lines/Curves/Squares), Streamlines (Flow/Edge/Superformula/Engraving), Composite (Layers/Mosaic/Quadtree), Dither Halftone, Shape Dither, Circle Packing, Differential Growth, and Tessellations (Isometric Y / Hex Aperture / Truchet Weave / Diamond Lattice).
- **Shape Dither** — Stamp circles, squares, stars, triangles, crosses, or uploaded SVG artwork on an image-sampled grid. Control aspect, resolution, tone levels, Floyd–Steinberg error diffusion, tone response, scale, gradient-following quarter-turn rotation, shape colour, and an export-only background colour.
- **Custom dither shapes** — Upload a single SVG shape directly, or bake up to 32 tone states from Cavalry; installed shapes persist in the library and appear as their own Shape Dither styles.
- **Raster-driven tessellations** — Four periodic vector patterns morph their geometry from each tile's average source tone. Scale, rotation, phase, response, inversion, and duplicate-edge cleanup remain editable per layer.
- **Poisson-disk sampler** — Blue-noise dart-throwing with a hard minimum-distance guarantee (`engine/sampling.py`), unlike the probabilistic thinning `Adaptive` uses; reuses all 7 styles like Voronoi/LBG/Adaptive.
- **Schema-driven params** — Every PFM's controls auto-generated from a typed schema (`engine/params.py`).
- **GPU acceleration** — Torch (MPS/CUDA) for nearest-site / weighted-centroid stages; numpy/scipy CPU fallback. Active backend shown in status bar.
- **Generators** — Procedural pattern generators distinct from image-driven PFMs (`/api/generate`).
- **Shape Field generator** — Build tiled patterns from a dynamic stack of circles, polygons, stars, diamonds, crosses, spirals, and waves across square, brick, hex, triangular, or jittered layouts; combine them as nested, alternating, connected, or overlapping motifs with modulation and seeded randomness.
- **Tabbed generator params** — The Generate panel groups a generator's params into tabs (one group shown at a time) instead of one long scroll; selecting a layer loads its current generation settings.
- **Deliberate generator switching** — Changing the generator never auto-redraws (even with Auto on); only same-generator parameter tweaks live-update. Applying a new generator waits for ✦ Generate.
- **Overwrite guard** — Pressing ✦ Generate on a layer that already holds a generation prompts a warning, offering to create a new layer instead of overwriting it.
- **Spokes & Circles pen distribution** — Optionally cycle the drawing-set's pens across the generator's elements: one pen per spoke, and circles either per-cluster or per-ring. Per-ring colors can be progressively staggered by a configurable number of pens across successive clusters. Choose dedicated pens for rays and borders; control forward/reverse order and the starting offset; changes follow the live enabled pen list and emit one Inkscape layer per colour.

## Live bridges
- **Cavalry capture layers** — Add an explicit Cavalry layer, then the Cavalry UI script (`cavalry/plotter-bridge.js`) streams debounced SVG frames into it while preserving its placement. Captures persist with the project; reopening the script asks whether to continue overwriting the live layer, start a new layer, or ignore that session.
- **Cavalry tessellation authoring** — Select up to 16 numeric attributes, give each light/dark boundaries, choose a lattice preset or custom repeat vectors, and bake a reusable 32-state vector pattern into PlotterForge. All parameters share one editable PlotterForge tone-response curve.
- **Cavalry mask parity** — SVG-native `<clipPath>` masks in captured frames are baked into the plotted geometry (plot preview, plot job, estimate, export), matching what Cavalry and the viewport show. Nested clips intersect; multi-shape clips union; full-page clips are pruned so circles keep native G2 arcs.
- **Cavalry reconnect** — A ⟳ button on any Cavalry layer re-arms it as the live capture target, undoing an earlier "Ignore this session": it clears the dismissal and rebinds the layer to whatever Cavalry script is currently posting (adopting a parked frame immediately if one is held).

## Composition (layers)
- **Layer stack** — Multiple stacked layers, each bound to a region or the whole image; reorder, duplicate, delete, toggle visibility.
- **Per-layer path finding** — Run a PFM per layer with independent params (`/pathfinding/generate`); switching a layer back to "Whole image" regenerates without the old region.
- **Display modes** — Show a layer as raster, pathfinding paths, or both.
- **Layer raster preview** — Served raster matches what the pathfinder analysed (aspect-correct, aligns with paths).
- **Transform** — Move and scale layers in the viewport with handles.
- **Rotate, Fit & Fill** — Rotate any layer numerically, fit the whole layer inside the padded drawing area, or fill the area and let export/plot clip overflow at the page edge.
- **Raster-layer path finding** — Generate strokes from an imported layer's own uncropped pixels; raster and paths share the same local transform and can be displayed separately or together.
- **Crop & mask** — Rectangle crop and rect/pen masks per layer; crop-to-content.
- **Occlusion** — Upper layers knock out lower layers along their actual mask/region outline (traced polygon), not just a bounding box.

## Drawing area & pens
- **Drawing Area** — Page size, units, orientation, padding, scaling mode, pen-width rescaling.
- **Drawing Sets (pens)** — Multi-pen sets with colour and per-pen size in mm (stroke width), edited in the Pens panel and reflected in the preview's stroke; items distributed across pens. Pen library presets.
- **Flat-nib preview** — Mark a pen as a flat/chisel nib (e.g. Pilot Parallel) held at a fixed angle; the on-screen preview approximates the calligraphic mark — full width perpendicular to the nib, thinning to a hairline when travel runs parallel to it. Toggle the whole width/nib preview off in View ▸ Pen width & nib to draw every stroke as a uniform thin line (raw centerline geometry). Preview-only: the exported/plotted SVG stays a plain centerline (the physical nib makes its own width).
- **Pen matching for imported/Cavalry layers** — Unlabelled `kind:"svg"` layers (raw Cavalry captures, no pen identity) preview and plot per pen: each stroke is colour-matched to the nearest enabled pen (nearest sRGB, effective stroke→fill→black), so it renders at that pen's colour/width, flows through flat-nib preview, and splits into per-pen plot passes and stats. Matching is done live at preview/split time (never baked into the layer), so editing a pen re-matches immediately; existing `inkscape:label`s always win. Fixes multi-pen plots silently dropping masked/Cavalry geometry.

## Viewport
- **Pan / zoom / fit** — Wheel zoom, drag pan, one-shot auto-fit, Fit button.
- **Snapping guides** — Alignment guides while moving layers.
- **View menu** — Top-bar View menu with Show guides (A4 boundary + A4/sheet center lines), Show bounds (layer bounds), and Pen width & nib (render pen stroke width + flat-nib calligraphy, off = uniform thin lines) toggles; all default on, session-level, independent of the workflow step. Snap lines stay visible regardless.

## Versions
- **Snapshot version control** — Save, load, rename, reorder, delete drawing snapshots with thumbnails.

## Feedback & status
- **Status bar** — Shows backend (GPU/CPU), current operation, progress bar, and plot elapsed/remaining/shape counts.
- **Useful errors** — Failures show the actual message (e.g. "Layer pathfinding error: …") in red in the status bar, never a bare "Error"; full text on hover.

## Output & plotting
- **Multi-layer SVG export** — mm-unit SVG with a viewBox; one Inkscape layer group per pen.
- **Composition export with progress + cancel** — composing/clipping a multi-layer page reports a per-layer progress bar over SSE and can be canceled mid-run (`/api/export/cancel`); the download runs via fetch with real error handling.
- **Direct plotting** — Drive the plotter from the app: estimate, plot, pause/resume, discard, stop; live progress over SSE (`/api/stream`).
- **Plot preview / emulator** — Animate the real plot order on the viewport before running: server returns ordered polylines per pen (`/api/plot/preview-paths`), the client retimes from speed settings (play/pause, 1/5/20/100× speed, timeline scrubber). The drawing is hidden so the animation plays onto a blank page. Travel moves show as faint dashed lines, pens draw in order in their own colours with pen-change markers on the timeline. Geometry mirrors the real plot exactly (only visible layers; crop/mask baked in; whole-SVG unless the drawing uses >1 pen).
- **Multi-pen plotting** — When a drawing uses more than one pen, the plot splits the SVG per pen and plots one pen at a time in enabled pen-list order: a pre-plot window confirms which pens are used, then between pens the plotter re-homes and a window prompts the operator to swap pens and confirm before continuing (copies nest all-pens-per-copy). Single-pen drawings plot unchanged.
- **Manual jog** — Manual plotter movement commands (`/api/manual`).
- **Wireless plotting** — Drive the iDraw from Mac Inkscape over a Tailscale `socat` serial bridge (see `bridge/`).

## Engineering
- **Performance profiling suite** — Deterministic CPU/MPS/CUDA/browser profiling with per-environment segmentation, named baselines, and warning-only trend reports that never fail CI (`tools/profile_suite.py`, see `docs/profiling.md`).

## Projects
- **Project management** — Create, open, rename, delete projects; stored under `~/.plotterforge/`.
- **Settings** — Persisted app settings (`/api/settings`).
