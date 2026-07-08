# Raster-Driven Tessellation Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable vector-state tessellation renderer and four built-in raster-driven tessellation PFMs.

**Architecture:** `engine/tessellation.py` owns the pattern types, state interpolation, lattice traversal, footprint tone sampling, and duplicate-line removal. `engine/tessellation_patterns.py` defines deterministic built-in state atlases, while `engine/pfm/tessellation.py` adapts any pattern to the existing PFM registry and parameter schema.

**Tech Stack:** Python 3.13, NumPy, Pillow, existing PFM/Geometry engine, pytest, Svelte 5 contract/e2e tests.

## Global Constraints

- A pattern has exactly 32 ordered states.
- Built-ins are Isometric Y, Hex Aperture, Truchet Weave, and Diamond Lattice.
- Tone is averaged over the actual lattice parallelogram; cells with mean alpha below `0.05` are skipped.
- The Studio controls are Columns, Rotation, Phase X, Phase Y, Tone Response, Invert Tone, and Remove Duplicate Lines.
- Generated output is ordinary plotter `Geometry`; existing pen distribution and drawing-area clipping remain unchanged.
- No new runtime dependency is added.
- The custom library, import endpoints, and Cavalry UI are implemented by the follow-on Cavalry authoring plan.

---

### Task 1: Pattern model and state interpolation

**Files:**
- Create: `engine/tessellation.py`
- Create: `tests/test_tessellation.py`

**Interfaces:**
- Produces: `TilePath`, `TileState`, `ParameterBinding`, `TessellationPattern`, `state_at_tone(pattern, tone)`.
- `TilePath.points` is an immutable tuple of `(float, float)` points; `TilePath.closed` is `bool`.
- `TessellationPattern` requires exactly 32 states and non-collinear vectors `a` and `b`.

- [ ] **Step 1: Write the failing model and interpolation tests**

```python
import pytest

from engine.tessellation import (
    ParameterBinding,
    TessellationPattern,
    TilePath,
    TileState,
    state_at_tone,
)


def state(x, *, closed=False, points=2):
    pts = tuple((x + i, x) for i in range(points))
    return TileState((TilePath(pts, closed),))


def pattern(states):
    return TessellationPattern(
        id="test", name="Test", source="builtin",
        a=(1.0, 0.0), b=(0.0, 1.0), bounds=(0.0, 0.0, 1.0, 1.0),
        states=tuple(states), bindings=(),
    )


def test_pattern_requires_32_states_and_nondegenerate_lattice():
    with pytest.raises(ValueError, match="32 states"):
        pattern([state(0.0)])
    with pytest.raises(ValueError, match="non-collinear"):
        TessellationPattern(
            id="bad", name="Bad", source="builtin",
            a=(1.0, 0.0), b=(2.0, 0.0), bounds=(0, 0, 1, 1),
            states=tuple(state(0.0) for _ in range(32)), bindings=(),
        )


def test_state_at_tone_interpolates_compatible_neighbors():
    p = pattern([state(float(i)) for i in range(32)])
    out = state_at_tone(p, 0.5)
    assert out.paths[0].points[0] == pytest.approx((15.5, 15.5))


@pytest.mark.parametrize("changed", [
    TileState((TilePath(((16, 16), (17, 16)), True),)),
    TileState((TilePath(((16, 16), (17, 16), (18, 16)), False),)),
    TileState((TilePath(((16, 16), (17, 16)), False), TilePath(((0, 0), (1, 1)), False))),
])
def test_state_at_tone_uses_nearest_whole_state_when_topology_changes(changed):
    states = [state(float(i)) for i in range(32)]
    states[16] = changed
    p = pattern(states)
    assert state_at_tone(p, 15.75 / 31) == changed
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run pytest tests/test_tessellation.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'engine.tessellation'`.

- [ ] **Step 3: Implement the immutable pattern types and interpolation**

```python
# engine/tessellation.py
from __future__ import annotations

from dataclasses import dataclass
import math

Point = tuple[float, float]
STATE_COUNT = 32


@dataclass(frozen=True)
class TilePath:
    points: tuple[Point, ...]
    closed: bool = False


@dataclass(frozen=True)
class TileState:
    paths: tuple[TilePath, ...]


@dataclass(frozen=True)
class ParameterBinding:
    layer_id: str
    attribute_id: str
    light: float
    dark: float
    curve: tuple[tuple[str, float], ...] | None = None


@dataclass(frozen=True)
class TessellationPattern:
    id: str
    name: str
    source: str
    a: Point
    b: Point
    bounds: tuple[float, float, float, float]
    states: tuple[TileState, ...]
    bindings: tuple[ParameterBinding, ...] = ()

    def __post_init__(self):
        if len(self.states) != STATE_COUNT:
            raise ValueError("Tessellation patterns require exactly 32 states")
        det = self.a[0] * self.b[1] - self.a[1] * self.b[0]
        if not math.isfinite(det) or abs(det) < 1e-9:
            raise ValueError("Tessellation lattice vectors must be finite and non-collinear")


def _compatible(a: TileState, b: TileState) -> bool:
    return len(a.paths) == len(b.paths) and all(
        pa.closed == pb.closed and len(pa.points) == len(pb.points)
        for pa, pb in zip(a.paths, b.paths)
    )


def state_at_tone(pattern: TessellationPattern, tone: float) -> TileState:
    pos = max(0.0, min(1.0, float(tone))) * (STATE_COUNT - 1)
    lo = int(math.floor(pos))
    hi = min(STATE_COUNT - 1, lo + 1)
    f = pos - lo
    a, b = pattern.states[lo], pattern.states[hi]
    if lo == hi or not _compatible(a, b):
        return a if f < 0.5 else b
    return TileState(tuple(
        TilePath(tuple(
            (ax + (bx - ax) * f, ay + (by - ay) * f)
            for (ax, ay), (bx, by) in zip(pa.points, pb.points)
        ), pa.closed)
        for pa, pb in zip(a.paths, b.paths)
    ))
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `uv run pytest tests/test_tessellation.py -q`

Expected: all tests in the new file pass.

- [ ] **Step 5: Commit the pattern model**

```bash
git add engine/tessellation.py tests/test_tessellation.py
git commit -m "feat: add tessellation pattern model"
```

---

### Task 2: Lattice traversal, footprint tone, and geometry placement

**Files:**
- Modify: `engine/tessellation.py`
- Modify: `tests/test_tessellation.py`

**Interfaces:**
- Consumes: `TessellationPattern`, `TileState`, `state_at_tone` from Task 1.
- Produces: `render_tessellation(work: PIL.Image.Image, pattern, values) -> list[Item]`.
- `values` keys are `columns`, `rotation`, `phase_x`, `phase_y`, `tone_response`, `invert_tone`, and `remove_duplicates`.

- [ ] **Step 1: Add failing placement and tone tests**

```python
import numpy as np
from PIL import Image

from engine.tessellation import render_tessellation


def constant_pattern(path=TilePath(((0.1, 0.5), (0.9, 0.5)))):
    s = TileState((path,))
    return TessellationPattern(
        id="constant", name="Constant", source="builtin",
        a=(1, 0), b=(0, 1), bounds=(0, 0, 1, 1),
        states=tuple(s for _ in range(32)), bindings=(),
    )


VALUES = dict(columns=2, rotation=0, phase_x=0, phase_y=0,
              tone_response=1, invert_tone=False, remove_duplicates=False)


def test_render_covers_page_and_scales_by_columns():
    work = Image.new("L", (100, 60), 128)
    items = render_tessellation(work, constant_pattern(), VALUES)
    assert items
    assert all(item.path is not None for item in items)
    xs = [x for item in items for x, _ in item.path.points]
    assert min(xs) < 0
    assert max(xs) > 100


def test_render_skips_transparent_cells():
    work = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    assert render_tessellation(work, constant_pattern(), VALUES) == []


def test_render_applies_gamma_and_inversion_to_geometry():
    states = tuple(state(float(i) / 31) for i in range(32))
    p = TessellationPattern("tone", "Tone", "builtin", (1, 0), (0, 1),
                            (0, 0, 1, 1), states, ())
    work = Image.fromarray(np.full((20, 20), 64, np.uint8), "L")
    normal = render_tessellation(work, p, {**VALUES, "columns": 1})[0]
    inverted = render_tessellation(work, p, {**VALUES, "columns": 1,
                                               "invert_tone": True})[0]
    assert normal.path.points != inverted.path.points
    assert normal.lum == pytest.approx(1 - 64 / 255, abs=0.02)


def test_rotation_and_phase_change_geometry_while_covering_page():
    work = Image.new("L", (80, 60), 128)
    base = render_tessellation(work, constant_pattern(), VALUES)
    moved = render_tessellation(
        work, constant_pattern(),
        {**VALUES, "rotation": 17, "phase_x": 0.25, "phase_y": -0.2},
    )
    assert base and moved
    assert moved[0].path.points != base[0].path.points
    for items in (base, moved):
        xs = [x for item in items for x, _ in item.path.points]
        ys = [y for item in items for _, y in item.path.points]
        assert min(xs) < 0 and max(xs) > work.width
        assert min(ys) < 0 and max(ys) > work.height
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `uv run pytest tests/test_tessellation.py -q`

Expected: import fails because `render_tessellation` is absent.

- [ ] **Step 3: Implement exact parallelogram sampling and placement**

Add to `engine/tessellation.py`:

```python
import numpy as np
from PIL import Image

from .geometry import Geometry, Item
from .image_ops import luminance

ALPHA_COVER_MIN = 0.05
MAX_TILES = 20_000


def _cell_mean(gray, alpha, origin, a, b):
    corners = np.asarray([origin, origin + a, origin + a + b, origin + b])
    x0 = max(0, int(math.floor(corners[:, 0].min())))
    y0 = max(0, int(math.floor(corners[:, 1].min())))
    x1 = min(gray.shape[1], int(math.ceil(corners[:, 0].max())))
    y1 = min(gray.shape[0], int(math.ceil(corners[:, 1].max())))
    if x1 <= x0 or y1 <= y0:
        return 1.0, 0.0
    yy, xx = np.mgrid[y0:y1, x0:x1]
    sample = np.stack((xx + 0.5 - origin[0], yy + 0.5 - origin[1]), axis=-1)
    inv = np.linalg.inv(np.column_stack((a, b)))
    uv = sample @ inv.T
    mask = ((uv[..., 0] >= 0) & (uv[..., 0] < 1)
            & (uv[..., 1] >= 0) & (uv[..., 1] < 1))
    if not mask.any():
        return 1.0, 0.0
    return float(gray[y0:y1, x0:x1][mask].mean()), float(alpha[y0:y1, x0:x1][mask].mean())


def _transformed_lattice(pattern, width, columns, rotation):
    base_a = np.asarray(pattern.a, dtype=float)
    base_b = np.asarray(pattern.b, dtype=float)
    scale = width / (max(1, int(columns)) * np.linalg.norm(base_a))
    theta = math.radians(float(rotation))
    rot = np.asarray(((math.cos(theta), -math.sin(theta)),
                      (math.sin(theta), math.cos(theta))))
    return rot @ (base_a * scale), rot @ (base_b * scale), rot * scale


def render_tessellation(work: Image.Image, pattern: TessellationPattern,
                         values: dict) -> list[Item]:
    gray, alpha = luminance(work)
    height, width = gray.shape
    a, b, artwork_transform = _transformed_lattice(
        pattern, width, values["columns"], values["rotation"])
    basis = np.column_stack((a, b))
    inv = np.linalg.inv(basis)
    phase = float(values["phase_x"]) * a + float(values["phase_y"]) * b
    page = np.asarray(((0, 0), (width, 0), (width, height), (0, height))) - phase
    ij = page @ inv.T
    imin, jmin = np.floor(ij.min(axis=0)).astype(int) - 2
    imax, jmax = np.ceil(ij.max(axis=0)).astype(int) + 2
    if (imax - imin + 1) * (jmax - jmin + 1) > MAX_TILES:
        raise ValueError("Tessellation exceeds the 20,000 tile limit")
    items = []
    for i in range(imin, imax + 1):
        for j in range(jmin, jmax + 1):
            origin = phase + i * a + j * b
            mean, cover = _cell_mean(gray, alpha, origin, a, b)
            if cover < ALPHA_COVER_MIN:
                continue
            darkness = 1.0 - mean
            mapped = 1.0 - darkness if values["invert_tone"] else darkness
            mapped = max(0.0, min(1.0, mapped)) ** float(values["tone_response"])
            tile = state_at_tone(pattern, mapped)
            for path in tile.paths:
                points = [tuple(origin + artwork_transform @ np.asarray(p)) for p in path.points]
                if len(points) >= 2:
                    items.append(Item(lum=darkness * cover,
                                      path=Geometry(points, closed=path.closed)))
    return deduplicate_items(items) if values["remove_duplicates"] else items
```

Declare `deduplicate_items` temporarily as identity so this task stays green:

```python
def deduplicate_items(items: list[Item], tolerance: float = 1e-6) -> list[Item]:
    return items
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `uv run pytest tests/test_tessellation.py -q`

Expected: all current tessellation tests pass.

- [ ] **Step 5: Commit the renderer**

```bash
git add engine/tessellation.py tests/test_tessellation.py
git commit -m "feat: render tone-driven tessellation lattices"
```

---

### Task 3: Duplicate segment removal and rechaining

**Files:**
- Modify: `engine/tessellation.py`
- Modify: `tests/test_tessellation.py`

**Interfaces:**
- Replaces the identity implementation of `deduplicate_items(items, tolerance=1e-6)`.
- Uses existing `engine.chain.chain_items` to rejoin surviving two-point paths.

- [ ] **Step 1: Add failing duplicate tests**

```python
from engine.geometry import Geometry, Item
from engine.tessellation import deduplicate_items


def test_duplicate_segments_are_removed_regardless_of_direction():
    items = [
        Item(0.2, path=Geometry([(0, 0), (1, 0), (2, 0)])),
        Item(0.8, path=Geometry([(2, 0), (1, 0)])),
    ]
    out = deduplicate_items(items)
    segments = [
        tuple(sorted((p0, p1)))
        for item in out if item.path
        for p0, p1 in zip(item.path.points, item.path.points[1:])
    ]
    assert segments.count(tuple(sorted(((1.0, 0.0), (2.0, 0.0))))) == 1
    assert segments.count(tuple(sorted(((0.0, 0.0), (1.0, 0.0))))) == 1


def test_nearby_but_distinct_segments_survive():
    items = [
        Item(0.5, path=Geometry([(0, 0), (1, 0)])),
        Item(0.5, path=Geometry([(0, 0.01), (1, 0.01)])),
    ]
    assert len(deduplicate_items(items, tolerance=1e-4)) == 2
```

- [ ] **Step 2: Run the duplicate tests and verify RED**

Run: `uv run pytest tests/test_tessellation.py -q`

Expected: the reversed duplicate remains.

- [ ] **Step 3: Implement canonical segment counting and rechaining**

```python
def deduplicate_items(items: list[Item], tolerance: float = 1e-6) -> list[Item]:
    from .chain import chain_items

    def key(point):
        return tuple(round(float(v) / tolerance) for v in point)

    segments = {}
    for item in items:
        if item.path is None or len(item.path.points) < 2:
            continue
        points = list(item.path.points)
        if item.path.closed:
            points.append(points[0])
        for p0, p1 in zip(points, points[1:]):
            k0, k1 = key(p0), key(p1)
            canonical = (k0, k1) if k0 <= k1 else (k1, k0)
            segments.setdefault(canonical, []).append((item.lum, p0, p1))
    survivors = []
    for occurrences in segments.values():
        lum, p0, p1 = occurrences[0]
        survivors.append(Item(lum=lum, path=Geometry([p0, p1])))
    return chain_items(survivors)
```

- [ ] **Step 4: Run focused and chain regression tests**

Run: `uv run pytest tests/test_tessellation.py tests/test_chain.py -q`

Expected: both files pass.

- [ ] **Step 5: Commit duplicate removal**

```bash
git add engine/tessellation.py tests/test_tessellation.py
git commit -m "feat: remove duplicate tessellation edges"
```

---

### Task 4: Four deterministic built-in state atlases

**Files:**
- Create: `engine/tessellation_patterns.py`
- Modify: `tests/test_tessellation.py`

**Interfaces:**
- Produces: `BUILTIN_PATTERNS: dict[str, TessellationPattern]` keyed by `tessellation_isometric_y`, `tessellation_hex_aperture`, `tessellation_truchet_weave`, and `tessellation_diamond_lattice`.
- Every factory emits exactly 32 deterministic `TileState` objects.

- [ ] **Step 1: Add failing built-in contract tests**

```python
from engine.tessellation_patterns import BUILTIN_PATTERNS


def test_builtins_have_stable_ids_and_32_distinct_endpoints():
    assert set(BUILTIN_PATTERNS) == {
        "tessellation_isometric_y", "tessellation_hex_aperture",
        "tessellation_truchet_weave", "tessellation_diamond_lattice",
    }
    for pattern in BUILTIN_PATTERNS.values():
        assert len(pattern.states) == 32
        assert pattern.states[0] != pattern.states[-1]


def test_builtins_render_deterministically_and_periodically():
    work = Image.new("L", (120, 80), 96)
    for pattern in BUILTIN_PATTERNS.values():
        first = render_tessellation(work, pattern, {**VALUES, "columns": 6})
        second = render_tessellation(work, pattern, {**VALUES, "columns": 6})
        assert first == second
        assert first
```

- [ ] **Step 2: Run the built-in tests and verify RED**

Run: `uv run pytest tests/test_tessellation.py -q`

Expected: import fails because `engine.tessellation_patterns` is absent.

- [ ] **Step 3: Implement the four normalized atlases**

Create helpers `_states(factory)`, `_poly(points, closed=False)`, and
`_arc(cx, cy, radius, start, end, count=12)`. Use these exact endpoint rules:

```python
def _isometric_y(t):
    inner = 0.08 + 0.24 * t
    outer = 0.52
    paths = []
    for angle in (-90, 30, 150):
        a = math.radians(angle)
        tangent = (-math.sin(a) * (0.05 + 0.05 * t),
                    math.cos(a) * (0.05 + 0.05 * t))
        start = (0.5 + inner * math.cos(a), 0.5 + inner * math.sin(a))
        end = (0.5 + outer * math.cos(a), 0.5 + outer * math.sin(a))
        paths.append(_poly(((start[0] + tangent[0], start[1] + tangent[1]),
                            (end[0] + tangent[0], end[1] + tangent[1]),
                            (end[0] - tangent[0], end[1] - tangent[1]),
                            (start[0] - tangent[0], start[1] - tangent[1])), True))
    return TileState(tuple(paths))


def _hex_aperture(t):
    r = 0.12 + 0.32 * t
    points = tuple((0.5 + r * math.cos(math.radians(60 * i - 30)),
                    0.5 + r * math.sin(math.radians(60 * i - 30))) for i in range(6))
    return TileState((_poly(points, True),))


def _truchet_weave(t):
    offset = 0.06 + 0.10 * t
    return TileState((
        _poly(_arc(0, 0, 0.5 - offset, 0, 90)),
        _poly(_arc(1, 1, 0.5 + offset, 180, 270)),
        _poly(_arc(1, 0, 0.5 - offset, 90, 180)),
        _poly(_arc(0, 1, 0.5 + offset, 270, 360)),
    ))


def _diamond_lattice(t):
    rx, ry = 0.16 + 0.30 * t, 0.46 - 0.20 * t
    return TileState((_poly(((0.5, 0.5 - ry), (0.5 + rx, 0.5),
                                  (0.5, 0.5 + ry), (0.5 - rx, 0.5)), True),))
```

Construct Isometric Y and Hex Aperture with oblique vectors
`a=(1, 0)`, `b=(0.5, sqrt(3)/2)`; Truchet with square vectors; and Diamond
Lattice with `a=(1, 0.5)`, `b=(-1, 0.5)`. Set bounds to `(0, 0, 1, 1)`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `uv run pytest tests/test_tessellation.py -q`

Expected: all tessellation tests pass.

- [ ] **Step 5: Commit built-ins**

```bash
git add engine/tessellation_patterns.py tests/test_tessellation.py
git commit -m "feat: add built-in tessellation patterns"
```

---

### Task 5: Register tessellation PFMs and expose Studio controls

**Files:**
- Create: `engine/pfm/tessellation.py`
- Modify: `engine/pfm/__init__.py`
- Modify: `frontend/src/components/panels/LayerStylePanel.svelte`
- Create: `tests/test_tessellation_pfm.py`
- Modify: `tests/test_frontend_contracts.py`

**Interfaces:**
- Consumes: `BUILTIN_PATTERNS`, `render_tessellation`.
- Produces: `register_tessellation_pattern(pattern) -> PFM`; custom-library work reuses this function.

- [ ] **Step 1: Write failing PFM and frontend contract tests**

```python
# tests/test_tessellation_pfm.py
from PIL import Image

from engine.canvas import DrawingArea
from engine.pens import DrawingSet
from engine.pfm import REGISTRY


def test_four_tessellation_pfms_are_registered_with_shared_controls():
    ids = {key for key in REGISTRY if key.startswith("tessellation_")}
    assert ids == {
        "tessellation_isometric_y", "tessellation_hex_aperture",
        "tessellation_truchet_weave", "tessellation_diamond_lattice",
    }
    names = {p.name for p in REGISTRY["tessellation_isometric_y"].params}
    assert {"columns", "rotation", "phase_x", "phase_y", "tone_response",
            "invert_tone", "remove_duplicates"} <= names


def test_tessellation_pfm_produces_paths():
    pfm = REGISTRY["tessellation_isometric_y"]
    drawing = pfm.run(Image.new("RGB", (96, 64), "#666"), DrawingArea(),
                      DrawingSet(), {"columns": 8})
    assert drawing.total() > 0
    assert sum(len(layer.paths) for layer in drawing.layers) > 0


def test_columns_keep_draft_and_full_tile_density_stable():
    pfm = REGISTRY["tessellation_hex_aperture"]
    image = Image.new("RGB", (900, 600), "#777")
    full = pfm.run(image, DrawingArea(), DrawingSet(), {"columns": 12})
    draft = pfm.run(image, DrawingArea(), DrawingSet(), {"columns": 12}, draft=True)
    assert abs(full.total() - draft.total()) <= 4
```

Add to `tests/test_frontend_contracts.py`:

```python
def test_layer_style_labels_tessellation_family(self):
    body = (ROOT / "frontend/src/components/panels/LayerStylePanel.svelte").read_text()
    self.assertIn('tessellation: "Tessellation"', body)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `uv run pytest tests/test_tessellation_pfm.py tests/test_frontend_contracts.py -q`

Expected: built-in IDs are absent and the frontend family label assertion fails.

- [ ] **Step 3: Register patterns through one reusable adapter**

```python
# engine/pfm/tessellation.py
from ..params import Param
from ..tessellation import TessellationPattern, render_tessellation
from ..tessellation_patterns import BUILTIN_PATTERNS
from ._params import SEED
from .base import PFM, register

PARAMS = SEED + [
    Param("columns", "int", 18, group="Lattice", min=2, max=160),
    Param("rotation", "angle", 0, group="Lattice", min=-180, max=180),
    Param("phase_x", "float", 0, group="Lattice", min=-1, max=1, step=0.01),
    Param("phase_y", "float", 0, group="Lattice", min=-1, max=1, step=0.01),
    Param("tone_response", "float", 1, group="Tone", min=0.1, max=5, step=0.05),
    Param("invert_tone", "bool", False, group="Tone"),
    Param("remove_duplicates", "bool", True, group="Plot"),
]


def register_tessellation_pattern(pattern: TessellationPattern) -> PFM:
    def generate(work, values, seed, bounds):
        return render_tessellation(work, pattern, values)
    return register(PFM(id=pattern.id, name=pattern.name,
                        family="tessellation", style="tessellation",
                        params=list(PARAMS), generate=generate))


for _pattern in BUILTIN_PATTERNS.values():
    register_tessellation_pattern(_pattern)
```

Import `.tessellation` from `engine/pfm/__init__.py` after `.grid`. Add
`tessellation: "Tessellation",` to `PFM_FAMILY_LABELS` in
`LayerStylePanel.svelte`.

- [ ] **Step 4: Run engine and frontend checks**

Run:

```bash
uv run pytest tests/test_tessellation.py tests/test_tessellation_pfm.py tests/test_frontend_contracts.py -q
cd frontend && npm run check
```

Expected: all tests pass and Svelte reports zero errors.

- [ ] **Step 5: Commit PFM integration**

```bash
git add engine/pfm/tessellation.py engine/pfm/__init__.py frontend/src/components/panels/LayerStylePanel.svelte tests/test_tessellation_pfm.py tests/test_frontend_contracts.py
git commit -m "feat: expose tessellation path-finding family"
```

---

### Task 6: Preview assets, end-to-end smoke coverage, and documentation

**Files:**
- Create: `tools/render_tessellation_previews.py`
- Create: `web/static/pfm-previews/tessellation_isometric_y.png`
- Create: `web/static/pfm-previews/tessellation_hex_aperture.png`
- Create: `web/static/pfm-previews/tessellation_truchet_weave.png`
- Create: `web/static/pfm-previews/tessellation_diamond_lattice.png`
- Modify: `frontend/e2e/c-smoke-pfm.spec.ts`
- Modify: `FEATURES.md`

**Interfaces:**
- Consumes: registered built-in PFMs and `engine.svg_io.to_svg`.
- Produces: 105×148 preview PNGs matching existing picker assets.

- [ ] **Step 1: Add an end-to-end tessellation smoke test**

```typescript
test("C8: tessellation styles render with schema and preview", async ({ request, baseURL }) => {
  const pfmId = "tessellation_isometric_y";
  const { layerId } = await setupPfmLayer(request, baseURL!, pfmId);
  await assertGeometry(request, baseURL!, layerId, pfmId, { columns: 8 });
  const schema = await (await request.get(`${baseURL}/api/pfm/${pfmId}/schema`)).json();
  expect(schema.params.map((p: { name: string }) => p.name)).toContain("tone_response");
  const preview = await request.get(`${baseURL}/static/pfm-previews/${pfmId}.png`);
  expect(preview.ok(), "tessellation preview should exist").toBeTruthy();
});
```

- [ ] **Step 2: Run the browser test and verify RED**

Run: `cd frontend && npx playwright test e2e/c-smoke-pfm.spec.ts --grep tessellation`

Expected: generation and schema assertions pass, then the preview request fails with 404.

- [ ] **Step 3: Add and run the deterministic preview renderer**

The script must create a 105×148 grayscale vertical gradient, run each built-in
PFM with `columns=10`, render its SVG through the existing preview path, and
write the four exact filenames listed above. Use a fixed seed of `0`, white
background, black 1 px paths, and no shadows.

Run: `uv run python tools/render_tessellation_previews.py`

Expected: four non-empty 105×148 PNG files appear under
`web/static/pfm-previews/`.

- [ ] **Step 4: Document the feature and run complete verification**

Add this bullet to the Path Finding section of `FEATURES.md`:

```markdown
- **Raster-driven tessellations** — Four periodic vector patterns morph their geometry from each tile's average source tone. Scale, rotation, phase, response, inversion, and duplicate-edge cleanup remain editable per layer.
```

Run:

```bash
uv run pytest tests -q
cd frontend && npm run check && npm run build
cd frontend && npx playwright test e2e/c-smoke-pfm.spec.ts --grep tessellation
```

Expected: Python suite, Svelte check, production build, and the focused browser test all pass.

- [ ] **Step 5: Commit previews and documentation**

```bash
git add tools/render_tessellation_previews.py web/static/pfm-previews/tessellation_*.png frontend/e2e/c-smoke-pfm.spec.ts FEATURES.md web/static/app
git commit -m "test: verify built-in tessellation workflow"
```
