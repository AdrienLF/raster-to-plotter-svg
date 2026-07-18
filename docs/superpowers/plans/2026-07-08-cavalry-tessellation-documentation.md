# Cavalry Tessellation Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish artist-facing Cavalry tessellation instructions in PlotterForge's local manual and a durable repository guide with the developer/API reference.

**Architecture:** Keep the in-app manual focused on the creative workflow in a new static HTML chapter that reuses `docs.css`. Put protocol, storage, limits, and maintenance details in one Markdown guide, then link both from the README and manual home page. Real Cavalry screenshots are optional enhancements and must never block complete written instructions.

**Tech Stack:** Markdown, static HTML/CSS, Python contract tests, PlotterForge's local Flask static server, in-app browser verification, optional macOS Cavalry screenshot capture.

## Global Constraints

- The manual chapter must be useful to an artist without requiring API knowledge.
- The repository guide must document both the artist workflow and developer contract.
- All UI labels, endpoint paths, limits, storage locations, and replacement semantics must match the implementation.
- Use only real Cavalry screenshots; never substitute generated or mocked application images.
- Written instructions must remain complete when screenshots cannot be captured.
- Do not change engine, API, or Cavalry behavior as part of this documentation work.

---

### Task 1: Repository guide and README discovery

**Files:**
- Create: `docs/cavalry-tessellations.md`
- Modify: `README.md`
- Modify: `tests/test_frontend_contracts.py`

**Interfaces:**
- Consumes: UI labels from `cavalry/plotter-bridge.js`, limits from `engine/tessellation_library.py`, and routes from `web/server.py`.
- Produces: the canonical repository guide and README links to both documentation surfaces.

- [ ] **Step 1: Add the failing documentation contract**

Add this method to `FrontendContractsTest`:

```python
def test_cavalry_tessellation_guides_are_linked_and_complete(self):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide_path = ROOT / "docs/cavalry-tessellations.md"
    self.assertIn("docs/cavalry-tessellations.md", readme)
    self.assertIn("/static/docs/tessellations.html", readme)
    self.assertTrue(guide_path.is_file())
    guide = guide_path.read_text(encoding="utf-8")
    for text in (
        "## Artist workflow", "## Lattice presets",
        "## Rebaking and recovery", "## Package format",
        "## HTTP API", "## Limits",
        "~/.plotterforge/tessellations/",
        "POST /api/tessellations/sessions", "GET /api/tessellations",
    ):
        self.assertIn(text, guide)
```

- [ ] **Step 2: Run the contract and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_frontend_contracts.py::FrontendContractsTest::test_cavalry_tessellation_guides_are_linked_and_complete -q
```

Expected: fail because the guide and README links do not exist.

- [ ] **Step 3: Write the repository guide**

Create `docs/cavalry-tessellations.md` with these exact headings:

```markdown
# Cavalry-authored tessellations
## Artist workflow
## Lattice presets
## Rebaking and recovery
## Package format
## HTTP API
## Limits
## Storage and startup
## Verification checklist
```

Document installation of `cavalry/plotter-bridge.js`; preparing one repeat unit;
numeric Light/Dark bindings; all four lattice presets; the shared 32-state bake;
PlotterForge controls; manifest version `1`; fields `layer_id`, `attribute_id`, `light`,
`dark`, and `curve`; all four HTTP endpoints; one-hour session expiry; 8 MiB per
SVG; 128 MiB total; 16 bindings; 2,000 paths; 200,000 flattened points;
coordinate magnitude 1,000,000; names of 1–80 visible characters; storage at
`~/.plotterforge/tessellations/<pattern-id>/`; atomic replacement; startup
registration; restored Cavalry values; and cached-SVG survival when a package is
missing.

- [ ] **Step 4: Add concise README discovery**

Add a `## Cavalry tessellation authoring` section near the PlotterForge
overview. Describe the bake in two short paragraphs and include:

```markdown
[Cavalry tessellation guide](docs/cavalry-tessellations.md)
[artist manual](http://localhost:7438/static/docs/tessellations.html)
```

- [ ] **Step 5: Run the focused contract and verify GREEN**

Run the Step 2 command. Expected: `1 passed`.

- [ ] **Step 6: Commit the repository guide**

```bash
git add README.md docs/cavalry-tessellations.md tests/test_frontend_contracts.py
git commit -m "docs: explain Cavalry tessellation authoring"
```

---

### Task 2: Artist-facing manual chapter

**Files:**
- Create: `web/static/docs/tessellations.html`
- Modify: `web/static/docs/index.html`
- Modify: `tests/test_frontend_contracts.py`

**Interfaces:**
- Consumes: `web/static/docs/docs.css` and the workflow documented in Task 1.
- Produces: `/static/docs/tessellations.html`, linked from the manual home page.

- [ ] **Step 1: Add the failing manual contract**

Extend the Task 1 test with:

```python
manual_home = (ROOT / "web/static/docs/index.html").read_text(encoding="utf-8")
manual_path = ROOT / "web/static/docs/tessellations.html"
self.assertIn('href="tessellations.html"', manual_home)
self.assertTrue(manual_path.is_file())
manual = manual_path.read_text(encoding="utf-8")
for text in (
    "Bake a pattern in Cavalry", "Add selected parameter", "Light", "Dark",
    "Rectangular", "Brick", "Hex/Isometric", "Custom", "Bake tessellation",
    "Apply / Regenerate", "Your original Cavalry values are restored",
):
    self.assertIn(text, manual)
```

- [ ] **Step 2: Run the contract and verify RED**

Run the Task 1 focused test. Expected: fail because the manual page and link do
not exist.

- [ ] **Step 3: Write the manual chapter**

Create a complete HTML5 page using `<link rel="stylesheet" href="docs.css">` and
the established `.wrap`, `.crumbs`, `.hero`, `.kicker`, `.lede`, `.cards`,
`.card`, `.steps`, `.note`, `table`, and `footer` patterns. Include:

- breadcrumb `Manual › Cavalry tessellations`;
- hero title `Bake a pattern in Cavalry`;
- a plain-language explanation of one repeat unit and 32 tone states;
- a numbered workflow from opening the bridge through Apply / Regenerate;
- a four-row lattice preset table;
- a PlotterForge controls table for Columns, Rotation, Phase X/Y, Tone Response,
  Invert Tone, and Remove Duplicate Lines;
- restored-value and safe-rebaking guidance;
- troubleshooting for selection, non-numeric attributes, invalid vectors,
  server failure, missing styles, and missing-package regeneration;
- the five-case real-Cavalry smoke checklist;
- footer links back to the manual, Creating strokes, and Fields.

- [ ] **Step 4: Link the chapter from the manual home page**

Add this card to the second `.cards` group:

```html
<a class="card" href="tessellations.html"><strong>◆ Cavalry tessellations</strong><p>Bake your own tone-responsive repeat patterns from selected Cavalry parameters.</p></a>
```

Add `· <a href="tessellations.html">Cavalry tessellations</a>` to the footer.

- [ ] **Step 5: Run the contract and verify GREEN**

Run the Task 1 focused test. Expected: `1 passed`.

- [ ] **Step 6: Commit the manual chapter**

```bash
git add web/static/docs/index.html web/static/docs/tessellations.html tests/test_frontend_contracts.py
git commit -m "docs: add Cavalry tessellations to the artist manual"
```

---

### Task 3: Real screenshots and rendered verification

**Files:**
- Optionally create: `web/static/docs/img/cavalry-tessellation-authoring.png`
- Optionally create: `web/static/docs/img/cavalry-tessellation-installed.png`
- Optionally modify: `web/static/docs/tessellations.html`

**Interfaces:**
- Consumes: `/Applications/Cavalry.app`, `cavalry/plotter-bridge.js`, the running PlotterForge at port 7438, and the manual chapter from Task 2.
- Produces: verified manual navigation and, when capture is possible, real screenshots containing no unrelated project data.

- [ ] **Step 1: Check screenshot prerequisites**

Confirm Cavalry exists at `/Applications/Cavalry.app`, the local manual responds,
and Cavalry's Scripts directory can be identified under the user's application
support directory. Do not modify the installed script without filesystem approval.

- [ ] **Step 2: Attempt the real-app capture**

Launch Cavalry with user approval. Open the Plotter Bridge and stage a disposable
composition containing no personal artwork. Capture:

1. the bridge's Tessellation controls with at least one numeric binding;
2. PlotterForge showing the installed custom pattern in the Tessellation family.

Crop to the relevant app window and save PNGs under `web/static/docs/img/`. If GUI
automation, accessibility, or screen-capture permission blocks this, stop the
screenshot attempt and report it; the written guide is the accepted fallback.

- [ ] **Step 3: Add successful captures to the manual**

Only when a real capture exists, add `<figure>` blocks with precise `alt` text and
captions next to the matching workflow steps. Do not add placeholder references.

- [ ] **Step 4: Run documentation verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_frontend_contracts.py -q
git diff --check
```

Expected: all frontend contract tests pass and `git diff --check` prints nothing.

- [ ] **Step 5: Verify the rendered local manual**

Using the in-app browser, reload
`http://localhost:7438/static/docs/index.html`, confirm the new card, open the
chapter, and inspect the hero, workflow, tables, troubleshooting, footer, and any
screenshots at desktop width. Check browser console logs for errors.

- [ ] **Step 6: Commit screenshot changes when present**

If screenshots were added:

```bash
git add web/static/docs/tessellations.html web/static/docs/img/cavalry-tessellation-authoring.png web/static/docs/img/cavalry-tessellation-installed.png
git commit -m "docs: illustrate Cavalry tessellation authoring"
```

If capture was blocked and browser verification changed no files, do not create
an empty commit; report the unavailable capture explicitly.
