# Spokes & Circles Pen Stagger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a configurable per-cluster stride that staggers per-ring pen colors in the Spokes & Circles generator while preserving current output by default.

**Architecture:** Extend the existing schema-driven Pens parameter group with one integer parameter. The generator will add `cluster_index * stagger` to the per-ring logical bucket before the existing offset/order mapping; the worker's current modulo mapping continues to handle the live enabled pen list.

**Tech Stack:** Python 3, `unittest`, existing generator `Param` schema, Svelte schema-driven parameter UI, Vite production build.

---

## File structure

- `engine/generate.py` — defines the Spokes & Circles schema and assigns logical pen buckets to generated lines.
- `tests/test_generate_pens.py` — asserts exact pen-bucket sequences and schema metadata.
- `FEATURES.md` — records the user-visible generator capability.

### Task 1: Add the staggered bucket rule

**Files:**
- Modify: `tests/test_generate_pens.py`
- Modify: `engine/generate.py:151-191`
- Modify: `engine/generate.py:246-257`

- [ ] **Step 1: Write the failing behavior and schema tests**

Add these methods to `SpokesPenBuckets` in `tests/test_generate_pens.py`:

```python
    def test_per_ring_stagger_advances_each_cluster(self):
        _, _, _, pens = spokes_and_circles(_params(
            pen_cycle=True, pen_circles="per_ring", pen_circle_stagger=1,
        ))
        self.assertEqual(pens, [0, 1, 1, 2, 2, 3])

    def test_per_ring_stagger_can_advance_multiple_pens(self):
        _, _, _, pens = spokes_and_circles(_params(
            pen_cycle=True, pen_circles="per_ring", pen_circle_stagger=2,
        ))
        self.assertEqual(pens, [0, 1, 2, 3, 4, 5])

    def test_per_ring_stagger_respects_reverse_order_and_offset(self):
        _, _, _, pens = spokes_and_circles(_params(
            pen_cycle=True,
            pen_circles="per_ring",
            pen_circle_stagger=1,
            pen_order="reverse",
            pen_offset=5,
        ))
        self.assertEqual(pens, [5, 4, 4, 3, 3, 2])

    def test_circle_stagger_schema_contract(self):
        params = {
            param.name: param
            for param in get_generator("spokes_and_circles")["params"]
        }
        stagger = params["pen_circle_stagger"]
        self.assertEqual(stagger.default, 0)
        self.assertEqual(stagger.min, 0)
        self.assertEqual(stagger.max, 32)
        self.assertEqual(stagger.group, "Pens")
```

The existing `test_per_ring_tags_line_up_across_spokes` remains the regression test for stagger `0`.

- [ ] **Step 2: Run the tests and verify the new cases fail**

Run:

```powershell
uv run python -m unittest tests.test_generate_pens
```

Expected: FAIL because the three stagger cases still produce aligned sequences and `pen_circle_stagger` is absent from the schema.

- [ ] **Step 3: Add the parameter and minimal assignment rule**

In `spokes_and_circles`, read the new value beside the existing circle pen mode:

```python
    circles_mode = p.get("pen_circles", "per_cluster")
    circle_stagger = max(0, int(p.get("pen_circle_stagger", 0)))
```

Replace the current `per_ring` assignment with:

```python
            elif cycle and circles_mode == "per_ring":
                circle_tags.append(bucket((c - 1) + s * circle_stagger))
```

Add the schema parameter immediately after `pen_circles` in `_SPOKES_PARAMS`:

```python
    Param("pen_circle_stagger", "int", 0, group="Pens", min=0, max=32,
          help="Shift each successive circle cluster by this many pens in per-ring mode"),
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run:

```powershell
uv run python -m unittest tests.test_generate_pens
```

Expected: all tests pass.

- [ ] **Step 5: Run adjacent generator regression tests**

Run:

```powershell
uv run python -m unittest tests.test_generate_crop tests.test_generate_pens
```

Expected: all tests pass, proving crop/tag threading and default output remain intact.

- [ ] **Step 6: Commit the generator change**

```powershell
git add engine/generate.py tests/test_generate_pens.py
git commit -m "feat: stagger circle pen colors"
```

### Task 2: Document and verify the feature

**Files:**
- Modify: `FEATURES.md`

- [ ] **Step 1: Update the feature inventory**

Replace the Spokes & Circles pen-distribution sentence in `FEATURES.md` with:

```markdown
- **Spokes & Circles pen distribution** — Optionally cycle the drawing-set's pens across the generator's elements: one pen per spoke, and circles either per-cluster or per-ring. Per-ring colors can be progressively staggered by a configurable number of pens across successive clusters. Choose dedicated pens for rays and borders; control forward/reverse order and the starting offset; changes follow the live enabled pen list and emit one Inkscape layer per colour.
```

- [ ] **Step 2: Run final verification**

From the repository root, run:

```powershell
uv run python -m unittest tests.test_generate_pens tests.test_generate_crop tests.test_frontend_contracts
Set-Location frontend
npm run check
Set-Location ..
git diff --check
```

Expected:

- all Python tests pass;
- `svelte-check` reports zero errors (existing accessibility warnings may remain);
- `git diff --check` prints no whitespace errors.

- [ ] **Step 3: Review the final diff**

Run:

```powershell
git status --short
git diff --stat
git diff -- FEATURES.md
```

Expected: only the feature inventory remains uncommitted after Task 1; the generator/test diff is already committed.

- [ ] **Step 4: Commit the feature inventory**

```powershell
git add FEATURES.md
git commit -m "docs: document circle pen staggering"
```
