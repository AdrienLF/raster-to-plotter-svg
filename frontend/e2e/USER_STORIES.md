# Plotter Studio — E2E User Stories

A library of user stories that drive the Playwright e2e tests. They serve three goals:

1. **Regression** — catch breakage as the software evolves.
2. **Performance** — measure (and later optimize) algorithm/UI timings; record with soft budgets.
3. **UI/UX** — give a concrete inventory of real flows to rethink the interface against.

Each story is tagged with its primary goal: **[R]** regression, **[P]** performance, **[U]** UX.
Story IDs appear in collected Playwright test names; some epics span multiple spec files.
Current coverage and the intentionally deferred backlog are recorded at the bottom.

Testing decisions:
- **Plotter:** mock serial + estimate-only (`PLOTTER_FAKE_SERIAL=1`). No real motion.
- **Performance:** record timings + soft budgets (`e2e/perf/budgets.json`); warn, don't hard-fail.
- **Framework:** Playwright driving the built Svelte app against a live, isolated Flask backend.

---

## Epic A — Project lifecycle & persistence

- **A1 [R]** New project: from a fresh app, "Project → New project…" with a name → it becomes current (●) and the canvas resets to empty.
- **A2 [R]** Switch project: with two projects, opening the other from the dropdown loads its image/layers/pens and updates the title.
- **A3 [R]** Rename project persists across reload.
- **A4 [R]** Delete project: confirmation required; afterwards it's gone and another project is current.
- **A5 [R]** Persistence across restart: a project with image + layers reloads composition/pens/versions intact after the backend restarts.
- **A6 [U]** First-run empty state: with no project/image, primary actions (Run path finding, Plot, Export) are disabled and the empty canvas is discoverable.

## Epic B — Image & SVG import

- **B1 [R]** Import raster (PNG/JPG) via File menu → image shows in viewport, name appears in MenuBar, `imageW/imageH` set.
- **B2 [R]** Import via ToolRail 🖼 button behaves identically to the menu.
- **B3 [R]** Import an `.svg` file → routed to `uploadSvg`, becomes an SVG layer (not a raster source).
- **B4 [R]** Re-import a different image replaces the source and clears stale region selection.
- **B5 [P]** Import a large image (e.g. 6000×4000) → upload + viewport render complete under soft budget; UI stays responsive.
- **B6 [U]** Unsupported file type is rejected gracefully (no crash, clear feedback).

## Epic C — Step 1: Path Finding (the core matrix)

- **C1 [R]** Add path-finding layer: "＋ Path finding" creates an empty layer, jumps to the editor, layer shows "stale".
- **C2 [R]** Run default PFM: with an image, Apply/Regenerate → status generating → clean, SVG appears, StatusBar shows shape count + length.
- **C3 [R]** Switch algorithm in the PFM dropdown reloads the param schema without losing the layer.
- **C4 [R]** Parameter round-trip: change an int/float/enum/bool param, regenerate, reload project → params persisted on the layer.
- **C5 [R]** Display-mode toggle Raster / Paths / Both changes what renders for that layer.
- **C6 [R]** "Occlude below" hides layers beneath in the composite.
- **C7 [R]** Smoke each sampler family produces non-empty geometry: **voronoi**, **lbg**, **adaptive** × representative styles (stippling, shapes, triangulation, tree, diagram, tsp). Data-driven over `/api/pfm/list`.
- **C8 [R]** Smoke each custom PFM: grid halftone, random stipple, hatch lines (+crosshatch), sketch lines/curves/squares, streamlines flow/edge/superformula, spiral, composite layers, mosaic rectangles.
- **C9 [P]** Per-PFM timing matrix: record `duration_ms` + shape count for every PFM on the same fixture; compare against soft budgets; emit a perf report artifact.
- **C10 [P]** GPU vs CPU: when `backend=torch-cuda`, voronoi/lbg beat a recorded CPU baseline (informational, not hard-fail).
- **C11 [R]** Error surfacing: a param combination that yields no points shows the layer error state, not a silent hang.
- **C12 [U]** Editor discoverability: from "＋ Path finding" a first-time user reaches a rendered result in the fewest clicks (record click count).

## Epic D — Regions (SAM2 segmentation)

- **D1 [R]** Create AI region: include / Alt-click exclude points, name + save → region appears in the layer's region dropdown.
- **D2 [R]** Run a PFM scoped to a region → geometry confined to the masked area; whole-image vs region differ.
- **D3 [R]** "Invert for background" produces the complementary mask.
- **D4 [R]** Delete region removes it and falls back to whole image.
- **D5 [P]** Segmentation predict latency recorded (gated on `/api/segmentation/status`; skipped, not failed, if model unavailable).
- **D6 [U]** Region point-editing affordance is clear (include vs exclude visually distinguishable).

## Epic E — Step 2: Generate from scratch

- **E1 [R]** Add generator layer: "＋ Generator" jumps to step 2 with the Generate panel and a target-layer selector.
- **E2 [R]** Generate spokes_and_circles with defaults → non-empty SVG in viewport.
- **E3 [R]** Auto-redraw: with Auto on, a param change regenerates after debounce; with Auto off, requires explicit Generate.
- **E4 [R]** Framework knobs (rotate_x/y/z, perspective, distortion, margin, seed) visibly change output; same seed → identical output (determinism).
- **E5 [R]** Generate into an existing layer vs a new layer both honored by the target selector.
- **E6 [P]** Generate timing recorded vs soft budget.
- **E7 [U]** Grouped/collapsible param sections keep the generate panel scannable (inventory groups).

## Epic F — Step 3: Composition (layer arrangement)

- **F1 [R]** Reorder layers with Up/Down changes z-order (top-of-list = top of render).
- **F2 [R]** Visibility checkbox toggles a layer in/out of the composite and gates Export/Plot enablement.
- **F3 [R]** Move layer via X/Y inputs (mm) and via drag produce the same placement; readout matches.
- **F4 [R]** Scale (%) and W/H (mm) resize the layer; aspect handling correct.
- **F5 [R]** Crop: "To content" tightens bounds; "Reset" restores; manual crop rect respected in output.
- **F6 [R]** Mask shapes (rectangle / oval / pen) limit layer visibility; Edit/Remove work.
- **F7 [R]** Duplicate (⧉) clones a layer with its style/params; delete (×) removes it.
- **F8 [R]** Alignment toolbar positions the selected layer against the page.
- **F9 [R]** Snapping to page center/edges/A4 guide engages within threshold while dragging.
- **F10 [U]** On-canvas handles vs numeric inputs: record which path is faster for a reposition+resize task.

## Epic G — Drawing area & page setup

- **G1 [R]** Preset (A5/A4/A3) + orientation set width/height; units (mm/cm/in/px) reinterpret inputs correctly.
- **G2 [R]** Padding (L/R/T/B) and scaling mode (crop/scale/stretch) affect the composed viewBox.
- **G3 [R]** Pen width (mm) changes rendered stroke width in preview and export.
- **G4 [R]** Clipping mode (Drawing/Page/None) and canvas/background colors apply.
- **G5 [U]** Changing the page after layers exist gives predictable, non-destructive results (inventory current behavior).

## Epic H — Pens & multi-pen distribution

- **H1 [R]** Load a pen library from the dropdown populates the pen list.
- **H2 [R]** Add/enable/disable/delete pens; rename + weight edits persist.
- **H3 [R]** Distribution type (luminance / even / random / single) changes per-pen usage % and split.
- **H4 [R]** Pen order (darkest/lightest/displayed/reversed) reorders assignment.
- **H5 [R]** Usage % reflects actual geometry after a regenerate.
- **H6 [U]** Pen panel readability with many pens (inventory).

## Epic I — Versions (snapshots)

- **I1 [R]** Save version with a name → appears with thumbnail + timestamp.
- **I2 [R]** Load a version restores the drawing AND its PFM params.
- **I3 [R]** Star rating, reorder (▲/▼), delete, and "Clear all" (with confirm) work.
- **I4 [R]** Thumbnails render (`/api/version-thumb`).
- **I5 [P]** Save/load version latency for a large drawing recorded.

## Epic J — Export

- **J1 [R]** Export SVG (combined) downloads a single valid SVG of visible layers; disabled when none visible.
- **J2 [R]** Export layers (zip) downloads a zip with one SVG per layer/pen split.
- **J3 [R]** Exported SVG dimensions/viewBox match the configured page (mm).
- **J4 [R]** Hidden layers are excluded from both exports.
- **J5 [P]** Export time for a heavy multi-layer drawing recorded.

## Epic K — Step 4: Plot (mock serial + estimate only)

- **K1 [R]** Estimate: with visible layers, the Estimate tab shows time + metrics grid via `/api/plot/estimate` (no hardware).
- **K2 [R]** Reordering mode (none / nearest / nearest+reverse / 2-opt) changes travel distance; nearest-family reduces travel vs none.
- **K3 [R]** Setup tab: set port (fake-serial), paper preset + Swap, pen up/down, save → persists.
- **K4 [R]** Speed / Pen-timing tabs persist drawing/travel/raise/lower speeds and delays.
- **K5 [R]** Start plot against the fake Grbl serial → state goes Plotting, progress streams, completes without real hardware.
- **K6 [R]** Stop mid-plot saves a resumable job; "Resume" continues from checkpoint; "Discard" clears it.
- **K7 [R]** Manual tab jog (↑↓←→ with step), Home, Pen up/down, Cycle, Motors off, Status emit the expected Grbl commands (assert on `/api/_test/serial-log`).
- **K8 [R]** Auto-rotate SVG when paper orientation differs is applied to the estimate/output.
- **K9 [P]** Path-reorder timing for a large drawing recorded; estimate stays non-blocking.
- **K10 [U]** Plot panel: the 6 tabs vs the most-common actions (Start/Estimate) — inventory for UX simplification.

## Epic L — Real-time stream & status

- **L1 [R]** SSE `/api/stream`: a long PFM run drives the StatusBar progress bar 0→100 then Idle.
- **L2 [R]** Backend badge shows GPU/CPU correctly per `/api/pfm/list` backend.
- **L3 [R]** Concurrent guard: starting a process while one runs is handled (queued or blocked, not corrupting state).
- **L4 [U]** Progress feedback latency: time from action to first progress event recorded.

## Epic M — Cross-cutting full journeys (flagship regression)

- **M1 [R+P]** Photo → multi-layer artwork: import → region → 2 path-finding layers (different PFMs) → compose/arrange → assign pens → export SVG. Records end-to-end time.
- **M2 [R]** Generate-only artwork: new project → generator layer → tweak framework → version save → export.
- **M3 [R+P]** Photo → plot dry-run: import → 1 PFM → estimate → start on fake serial → stop → resume → finish.
- **M4 [U]** New-user happy path: measure clicks/steps from blank app to first exported SVG (UX baseline metric).

---

## Coverage status

The Playwright suite contains 84 tests covering 73 of the 86 story IDs above. Data-driven C7/C8 cases account for multiple tests under a single story ID.

### Deferred stories

- **A5:** Persistence across a backend restart, including composition, pens, and versions.
- **D1-D6:** SAM2 region creation, confinement, inversion, deletion, latency, and editing UX.
- **F6:** Composition masks.
- **F8:** Alignment toolbar behavior.
- **F9:** On-canvas snapping.
- **F10:** Handle-versus-input UX benchmark.
- **H6:** Many-pen readability inventory.
- **K10:** Plot-panel action hierarchy inventory.

These are backlog items, not implied coverage. A story moves out of this list only when its named Playwright test runs in the complete suite.
