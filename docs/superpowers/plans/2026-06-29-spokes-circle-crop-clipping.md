# Spokes & Circles Crop Clipping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every ray and structural spoke segment from inside every Spokes & Circles cluster crop.

**Architecture:** Normalize approximately closed convex rings in the shared `convex_interval` clipper, then route structural spokes through the same crop polygons as background rays. Keep circle outlines as ordinary generated paths so preview, SVG export, and plotting consume identical baked geometry.

**Tech Stack:** Python 3.13, `unittest` assertions collected by pytest, existing generator geometry helpers.

---

## File Map

- Create `tests/test_generate_crop.py`: focused geometry and generator regression coverage.
- Modify `engine/genframe.py`: normalize convex polygon rings before half-plane clipping.
- Modify `engine/generate.py`: apply every cluster crop to structural spokes as well as rays.
- Preserve `docs/superpowers/plans/2026-06-29-spokes-circle-crop-clipping.md`: executable implementation record.

### Task 1: Make convex clipping robust for approximately closed rings

**Files:**
- Create: `tests/test_generate_crop.py`
- Modify: `engine/genframe.py:318-345`
- Test: `tests/test_generate_crop.py`

- [ ] **Step 1: Write the failing ring and ray-leak regression tests**

Create `tests/test_generate_crop.py` with:

```python
import math
import unittest

from engine.generate import (
    get_generator,
    make_circle,
    rotate,
    spokes_and_circles,
    translate,
)
from engine.genframe import convex_interval
from engine.params import defaults


def cluster_crops(params, page_width, page_height):
    crops = []
    angle = 360.0 / params["spokes"]
    for index in range(params["spokes"]):
        spoke_angle = angle * index + 90 + params["spoke_rotation"]
        crop = make_circle(params["circle_segments"], params["crop_radius"])
        crop = rotate(crop, params["circle_rotation"] + 90)
        crop = translate(crop, 0, -params["spoke_length"])
        crop = translate(
            rotate(crop, spoke_angle),
            page_width / 2,
            page_height / 2,
        )
        crops.append(crop)
    return crops


def positive_overlap(line, crop):
    for start, end in zip(line, line[1:]):
        interval = convex_interval(start, end, crop)
        if interval is not None and interval[1] - interval[0] > 1e-8:
            return interval
    return None


class ConvexIntervalTest(unittest.TestCase):
    def test_approximately_closed_ring_matches_exactly_closed_ring(self):
        ring = make_circle(90, 3.8)
        ring = rotate(ring, 90)
        ring = translate(ring, 0, -6)
        ring = rotate(ring, 180)
        ring = translate(ring, 14.85, 21)
        exact_ring = ring[:-1] + [ring[0]]
        start = (14.85, 21.0)
        end = (12.17995222430975, 39.0)

        expected = convex_interval(start, end, exact_ring)
        actual = convex_interval(start, end, ring)

        self.assertIsNotNone(expected)
        self.assertIsNotNone(actual)
        self.assertAlmostEqual(actual[0], expected[0])
        self.assertAlmostEqual(actual[1], expected[1])


class SpokesAndCirclesCropTest(unittest.TestCase):
    def params(self):
        return defaults(get_generator("spokes_and_circles")["params"])

    def assert_lines_outside_crops(self, lines, crops):
        for line_index, line in enumerate(lines):
            for crop_index, crop in enumerate(crops):
                self.assertIsNone(
                    positive_overlap(line, crop),
                    f"line {line_index} overlaps crop {crop_index}",
                )

    def test_background_rays_do_not_leak_into_overlapping_cluster_crops(self):
        params = self.params()
        params.update({"circles": 0, "draw_spokes": False})

        lines, page_width, page_height = spokes_and_circles(params)

        self.assertGreater(len(lines), 0)
        self.assert_lines_outside_crops(
            lines,
            cluster_crops(params, page_width, page_height),
        )
```

- [ ] **Step 2: Run the two tests and verify they fail for the diagnosed reason**

Run:

```powershell
uv run python -m pytest tests/test_generate_crop.py -v
```

Expected: both tests fail. The first reports `actual` is unexpectedly `None`; the second reports at least one generated line overlapping a cluster crop.

- [ ] **Step 3: Normalize the convex ring in `convex_interval`**

Replace the beginning and edge construction of `convex_interval` in `engine/genframe.py` with:

```python
def convex_interval(p0, p1, poly):
    """Parametric interval [u0,u1] of segment p0->p1 that lies inside the convex
    polygon `poly` (clip against each edge half-plane). None if no overlap.
    Reads only [0],[1] of each point, so works for 2D or 3D points."""
    vertices = list(poly)
    if len(vertices) >= 2 and all(
        math.isclose(vertices[0][axis], vertices[-1][axis], abs_tol=1e-9)
        for axis in (0, 1)
    ):
        vertices.pop()
    if len(vertices) < 3:
        return None

    n = len(vertices)
    cx = sum(pt[0] for pt in vertices) / n
    cy = sum(pt[1] for pt in vertices) / n
    x0, y0 = p0[0], p0[1]
    dx, dy = p1[0] - x0, p1[1] - y0
    edges = list(zip(vertices, vertices[1:] + vertices[:1]))
    u0, u1 = 0.0, 1.0
    for a, b in edges:
        ex, ey = b[0] - a[0], b[1] - a[1]
        s = 1.0 if (ex * (cy - a[1]) - ey * (cx - a[0])) >= 0 else -1.0
        c0 = s * (ex * (y0 - a[1]) - ey * (x0 - a[0]))
        c1 = s * (ex * dy - ey * dx)
        if abs(c1) < 1e-12:
            if c0 < 0:
                return None
        else:
            t = -c0 / c1
            if c1 > 0:
                u0 = max(u0, t)
            else:
                u1 = min(u1, t)
    return (u0, u1) if u0 <= u1 else None
```

- [ ] **Step 4: Re-run the focused tests and verify they pass**

Run:

```powershell
uv run python -m pytest tests/test_generate_crop.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit the shared clipper fix**

```powershell
git add docs/superpowers/plans/2026-06-29-spokes-circle-crop-clipping.md tests/test_generate_crop.py engine/genframe.py
git commit -m "fix: close polygon crops robustly"
```

### Task 2: Crop structural spokes with every cluster

**Files:**
- Modify: `tests/test_generate_crop.py`
- Modify: `engine/generate.py:100-158`
- Test: `tests/test_generate_crop.py`

- [ ] **Step 1: Write the failing structural-spoke regression test**

Append this method to `SpokesAndCirclesCropTest`:

```python
    def test_structural_spoke_stops_at_its_cluster_crop(self):
        params = self.params()
        params.update({"spokes": 1, "circles": 0, "rays": 0})

        lines, page_width, page_height = spokes_and_circles(params)
        crops = cluster_crops(params, page_width, page_height)

        self.assertEqual(len(lines), 1)
        self.assert_lines_outside_crops(lines, crops)
        cluster_center = (
            sum(point[0] for point in crops[0][:-1]) / (len(crops[0]) - 1),
            sum(point[1] for point in crops[0][:-1]) / (len(crops[0]) - 1),
        )
        self.assertGreater(math.dist(lines[0][-1], cluster_center), 1.0)
```

- [ ] **Step 2: Run the new test and verify it fails because the spoke reaches inside the crop**

Run:

```powershell
uv run python -m pytest tests/test_generate_crop.py::SpokesAndCirclesCropTest::test_structural_spoke_stops_at_its_cluster_crop -v
```

Expected: FAIL with `line 0 overlaps crop 0`.

- [ ] **Step 3: Route spokes through the cluster crop sequence**

In `spokes_and_circles`, build structural spokes before the cluster loop:

```python
    spoke_lines: list[Line] = []
    if p["draw_spokes"]:
        for s in range(spokes):
            sp_ang = angle * s + 90 + float(p["spoke_rotation"])
            spoke = [(0.0, 0.0), (0.0, -spoke_len)]
            spoke = translate(rotate(spoke, sp_ang), cx_pg, cy_pg)
            spoke_lines.append(spoke)

    pattern: list[Line] = []
    for s in range(spokes):
        sp_ang = angle * s + 90 + float(p["spoke_rotation"])
```

Remove the old `if p["draw_spokes"]` block from inside the cluster loop. After each crop polygon is built, crop both straight-line collections:

```python
        ray_lines = cull_inside_polygon(ray_lines, crop)
        spoke_lines = cull_inside_polygon(spoke_lines, crop)
```

Before appending rays, prepend the cropped spokes to the output:

```python
    pattern = spoke_lines + pattern
    pattern.extend(ray_lines)
```

- [ ] **Step 4: Run all crop regressions and verify they pass**

Run:

```powershell
uv run python -m pytest tests/test_generate_crop.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit the spoke behavior change**

```powershell
git add tests/test_generate_crop.py engine/generate.py
git commit -m "fix: crop spokes inside circle clusters"
```

### Task 3: Verify the repository

**Files:**
- Verify: `engine/genframe.py`
- Verify: `engine/generate.py`
- Verify: `tests/test_generate_crop.py`

- [ ] **Step 1: Check patch formatting**

Run:

```powershell
git diff --check HEAD~2
```

Expected: exit 0 with no output.

- [ ] **Step 2: Run the complete Python test suite**

Run:

```powershell
uv run python -m pytest -q
```

Expected: all tests pass with no failures.

- [ ] **Step 3: Inspect final repository state**

Run:

```powershell
git status --short
git log -3 --oneline
```

Expected: no uncommitted files; the two implementation commits appear above the design commit.
