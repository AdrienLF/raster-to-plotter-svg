# Exceptional Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn PlotterForge's accurate six-page manual into a navigable, reproducible product handbook with flagship tutorials, complete generated PFM reference, operator troubleshooting, current screenshots, and automated drift checks.

**Architecture:** Keep the manual dependency-free and served from `web/static/docs/`. A shared `docs.js` injects navigation, search, table-of-contents, and page metadata into semantic static HTML, so every page remains readable without JavaScript. Python utilities validate the manual and generate the PFM catalog directly from the engine registry.

**Tech Stack:** Static HTML/CSS/vanilla JavaScript, Python 3.13 standard library, PlotterForge PFM registry, unittest/pytest, in-app browser verification.

## Global Constraints

- Do not add runtime or frontend package dependencies.
- Keep all manual pages usable as plain static HTML when JavaScript is disabled.
- Treat engine schemas as the source of truth for PFM names, defaults, ranges, choices, groups, and help text.
- Use only real PlotterForge screenshots; never present generated application chrome as the real app.
- Preserve the existing dark visual language and artist-focused voice.
- Keep the current Compose → Generate → Plot terminology.

---

### Task 1: Documentation contracts and shared shell

**Files:**
- Create: `tests/test_docs.py`
- Create: `web/static/docs/docs.js`
- Modify: `web/static/docs/docs.css`
- Modify: `web/static/docs/*.html`

**Interfaces:**
- Consumes: static manual pages under `web/static/docs/`.
- Produces: `window.PLOTTER_DOCS_PAGES`, a shared page index used by navigation and search.

- [ ] **Step 1: Write failing contracts**

Add tests asserting every manual page loads `docs.js`, has one `main`, exposes a unique description, participates in the shared page index, and has valid local links/images. Assert the shell source contains search, table-of-contents, active-page, and keyboard-focus behavior.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_docs.py -q`

Expected: failures for missing `docs.js`, page metadata, and shell landmarks.

- [ ] **Step 3: Implement the dependency-free shell**

Create a stable page registry for Home, Tutorials, Create, Compose, Fields, Plot, Tessellations, Reference, Troubleshooting, and What's New. Inject a skip link, header, sidebar, search dialog, page TOC, previous/next navigation, and version label. Add responsive, focus-visible, print, callout, parameter-table, and annotated-figure styles.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_docs.py tests/test_frontend_contracts.py -q`

Expected: all documentation and frontend contracts pass.

### Task 2: Reproducible flagship tutorials and decision support

**Files:**
- Create: `web/static/docs/tutorials.html`
- Create: `web/static/docs/choose-a-style.html`
- Create: `web/static/docs/img/tutorial-source.png`
- Modify: `web/static/docs/index.html`
- Modify: `README.md`

**Interfaces:**
- Consumes: `frontend/e2e/assets/sample.png`, current Shape Dither and composition screenshots.
- Produces: task-based routes for photo-to-SVG, generator poster, and Shape Dither workflows with exact settings and observable checkpoints.

- [ ] **Step 1: Extend failing content contracts**

Assert that tutorials cover source asset, exact settings, checkpoint, expected result, export, estimate, and pre-flight. Assert style guidance addresses portraits, bold markers, single-line work, geometric posters, multiple pens, and plotting-time reduction.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_docs.py -q`

Expected: missing tutorial and decision-guide pages.

- [ ] **Step 3: Write the tutorials and selection guide**

Create three full journeys: photo → Voronoi Stippling → SVG, generator → multi-pen poster, and image → Shape Dither. Include exact values, success signals, recovery notes, time/complexity expectations, and links to the bundled sample. Add a goal/medium/time comparison table and starting recipes.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_docs.py -q`

Expected: tutorial and decision-guide contracts pass.

### Task 3: Generated PFM reference

**Files:**
- Create: `tools/build_docs_reference.py`
- Create: `web/static/docs/reference.html`
- Modify: `tests/test_docs.py`
- Modify: `web/static/docs/create.html`

**Interfaces:**
- Consumes: `engine.pfm.REGISTRY` and each `Param` schema.
- Produces: `render_reference() -> str` and a deterministic `reference.html` containing all built-in PFMs and parameter metadata.

- [ ] **Step 1: Write failing generator tests**

Assert all registry IDs/names appear exactly once, parameter rows include group/type/default/range-or-choices/help, output is deterministic, and the checked-in reference equals `render_reference()`.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_docs.py -q`

Expected: import failure for `tools.build_docs_reference`.

- [ ] **Step 3: Implement and generate the reference**

Render family sections, preview images, concise family guidance, parameter tables, and anchors from the live registry. Add `--check` and output-path CLI modes. Link the catalog from Creating Strokes.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/python tools/build_docs_reference.py --check && .venv/bin/python -m pytest tests/test_docs.py -q`

Expected: generated reference is current and tests pass.

### Task 4: Operator handbook, troubleshooting, and release orientation

**Files:**
- Create: `web/static/docs/troubleshooting.html`
- Create: `web/static/docs/whats-new.html`
- Modify: `web/static/docs/plot.html`
- Modify: `web/static/docs/compose.html`
- Modify: `README.md`

**Interfaces:**
- Consumes: actual setup/runtime messages and documented plot recovery semantics.
- Produces: symptom → cause → action tables and a physical pre-flight/calibration checklist.

- [ ] **Step 1: Add failing operator contracts**

Assert coverage for unsupported files, EXIF/aspect, empty output, dense/slow output, SAM setup, GPU fallback, clipping, serial ports, bridge conflicts, homing, pen heights, jams, Stop/Resume, and diagnostics collection.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_docs.py -q`

Expected: troubleshooting and release pages missing.

- [ ] **Step 3: Implement operator guidance**

Add symptom-led tables, a first-plot calibration sequence, safe dry-run and recovery procedures, and a short release page covering raster layers, Shape Dither, and EXIF handling. Separate artist/operator/developer routes in the README.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_docs.py tests/test_frontend_contracts.py -q`

Expected: all contracts pass.

### Task 5: Visual refresh and automated drift protection

**Files:**
- Create: `tools/check_docs.py`
- Modify: `web/static/docs/img/overview.png`
- Modify: `web/static/docs/img/composition.png`
- Modify: `web/static/docs/img/shape-dither.png`
- Modify: `tests/test_docs.py`

**Interfaces:**
- Consumes: manual HTML, screenshots, generated reference, current PFM registry.
- Produces: `check_docs() -> list[str]`, where an empty list means the manual is internally consistent.

- [ ] **Step 1: Write failing drift tests**

Assert no broken local references, every image has useful alt text and dimensions, screenshots use supported PNG/JPEG signatures, no stale PFM counts remain, every PFM is represented in the generated reference, and no page is omitted from navigation.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_docs.py -q`

Expected: failure for missing `tools.check_docs` and stale screenshot requirements.

- [ ] **Step 3: Refresh screenshots and implement checker**

Capture the current Rotate/Fit/Fill composition UI and a contradiction-free Shape Dither crop from an isolated local PlotterForge project. Implement a standard-library checker and CLI with non-zero exit on drift.

- [ ] **Step 4: Render and browser-verify every page**

Run the isolated PlotterForge server, open all manual routes, verify every image has non-zero natural dimensions, exercise search and keyboard dismissal, check responsive navigation, and inspect key screenshots visually.

- [ ] **Step 5: Run complete verification**

Run: `.venv/bin/python tools/build_docs_reference.py --check`

Run: `.venv/bin/python tools/check_docs.py`

Run: `.venv/bin/python -m pytest tests/test_docs.py tests/test_frontend_contracts.py -q`

Run: `git diff --check`

Expected: all commands exit 0 with no broken links, stale generated output, or test failures.
