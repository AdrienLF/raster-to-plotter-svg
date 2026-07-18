# Shape Field Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a selectable Shape Field generator with a dedicated dynamic shape-stack editor, five lattice layouts, four combination modes, modulation, and seeded randomness.

**Architecture:** Keep scalar generator settings in the existing schema system while Shape Field owns a sanitized `shape_layers` array. A focused backend module generates and combines plotter-ready polylines; additive schema metadata lets the Generate page select a dedicated Svelte editor without changing Spokes & Circles.

**Tech Stack:** Python 3.13, Flask, unittest/pytest, Svelte 5, TypeScript, Vite, Playwright.

---

## File Map

- Create `engine/shape_field.py`: validation, primitives, lattices, modulation, random variation, output budgeting, and generator entry point.
- Modify `engine/generate.py`: register Shape Field and export shared page schema.
- Modify `web/server.py`: generator-specific normalization and additive schema metadata.
- Create `tests/test_shape_field.py`: backend geometry and API contract tests.
- Modify `frontend/src/lib/types.ts`: `ShapeLayerT` type.
- Modify `frontend/src/lib/state.svelte.ts`: generator editor metadata.
- Modify `frontend/src/lib/api.ts`: preserve Shape Field structured defaults and clear them for other algorithms.
- Create `frontend/src/components/generate/ShapeFieldEditor.svelte`: dedicated field controls and dynamic layer cards.
- Modify `frontend/src/components/panels/GeneratePanel.svelte`: choose the dedicated editor.
- Modify `tests/test_frontend_contracts.py`: state/API/editor wiring assertions.
- Modify `frontend/e2e/e-generator.spec.ts`: user-visible Shape Field generation flow.
- Modify `FEATURES.md` and `frontend/e2e/USER_STORIES.md`: feature and regression inventory.

### Task 1: Shape-layer normalization and primitive geometry

**Files:**
- Create: `engine/shape_field.py`
- Create: `tests/test_shape_field.py`

- [ ] **Step 1: Write failing normalization and primitive tests**

Create `tests/test_shape_field.py` with these initial tests:

```python
import math
import unittest

from engine.shape_field import (
    DEFAULT_SHAPE_LAYERS,
    SHAPE_TYPES,
    normalize_shape_layers,
    primitive,
)


class ShapeLayerNormalizationTest(unittest.TestCase):
    def test_defaults_cover_extended_shape_palette(self):
        self.assertEqual(
            SHAPE_TYPES,
            ("circle", "polygon", "star", "diamond", "cross", "spiral", "wave"),
        )
        self.assertEqual([layer["type"] for layer in DEFAULT_SHAPE_LAYERS], ["circle", "star", "wave"])

    def test_invalid_values_are_sanitized_and_unknown_keys_are_dropped(self):
        [layer] = normalize_shape_layers([
            {
                "id": "custom",
                "enabled": "yes",
                "type": "bogus",
                "scale": float("nan"),
                "sides": 99,
                "repeat_count": 999,
                "unknown": "drop me",
            }
        ])
        self.assertEqual(layer["id"], "custom")
        self.assertTrue(layer["enabled"])
        self.assertEqual(layer["type"], "circle")
        self.assertTrue(math.isfinite(layer["scale"]))
        self.assertEqual(layer["sides"], 24)
        self.assertEqual(layer["repeat_count"], 24)
        self.assertNotIn("unknown", layer)

    def test_empty_shape_stack_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least one enabled shape layer"):
            normalize_shape_layers([])


class ShapePrimitiveTest(unittest.TestCase):
    def test_closed_and_open_shape_contracts(self):
        layer = normalize_shape_layers([{}])[0]
        for shape_type in SHAPE_TYPES:
            with self.subTest(shape_type=shape_type):
                line = primitive({**layer, "type": shape_type}, 2.0)
                self.assertGreaterEqual(len(line), 2)
                self.assertTrue(all(math.isfinite(value) for point in line for value in point))
                if shape_type in {"circle", "polygon", "star", "diamond", "cross"}:
                    self.assertEqual(line[0], line[-1])
                else:
                    self.assertNotEqual(line[0], line[-1])
```

- [ ] **Step 2: Verify the new tests fail because the module does not exist**

Run:

```powershell
uv run python -m pytest tests/test_shape_field.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'engine.shape_field'`.

- [ ] **Step 3: Implement normalized shape-layer data**

In `engine/shape_field.py`, define:

```python
from __future__ import annotations

import math
import random
from copy import deepcopy

from .params import Param, validate

Point = tuple[float, float]
Line = list[Point]

SHAPE_TYPES = ("circle", "polygon", "star", "diamond", "cross", "spiral", "wave")

SHAPE_LAYER_DEFAULT = {
    "id": "shape",
    "enabled": True,
    "type": "circle",
    "scale": 0.72,
    "rotation": 0.0,
    "offset_x": 0.0,
    "offset_y": 0.0,
    "repeat_count": 1,
    "repeat_scale": 0.78,
    "repeat_rotation": 18.0,
    "segments": 48,
    "sides": 6,
    "points": 7,
    "inner_ratio": 0.45,
    "aspect": 1.0,
    "arm_width": 0.32,
    "turns": 2.5,
    "cycles": 3.0,
    "amplitude": 0.45,
}

DEFAULT_SHAPE_LAYERS = [
    {**SHAPE_LAYER_DEFAULT, "id": "circle-1", "type": "circle", "scale": 0.78},
    {**SHAPE_LAYER_DEFAULT, "id": "star-1", "type": "star", "scale": 0.58, "rotation": 18.0},
    {**SHAPE_LAYER_DEFAULT, "id": "wave-1", "type": "wave", "scale": 0.46, "rotation": 45.0},
]


def _number(value, default, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return max(low, min(high, number))


def _integer(value, default, low, high):
    return int(round(_number(value, default, low, high)))


def _boolean(value):
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def normalize_shape_layer(raw, index):
    raw = raw if isinstance(raw, dict) else {}
    default = SHAPE_LAYER_DEFAULT
    shape_type = str(raw.get("type", default["type"]))
    return {
        "id": str(raw.get("id") or f"shape-{index + 1}"),
        "enabled": _boolean(raw.get("enabled", default["enabled"])),
        "type": shape_type if shape_type in SHAPE_TYPES else default["type"],
        "scale": _number(raw.get("scale"), default["scale"], 0.0, 4.0),
        "rotation": _number(raw.get("rotation"), default["rotation"], -360.0, 360.0),
        "offset_x": _number(raw.get("offset_x"), default["offset_x"], -4.0, 4.0),
        "offset_y": _number(raw.get("offset_y"), default["offset_y"], -4.0, 4.0),
        "repeat_count": _integer(raw.get("repeat_count"), default["repeat_count"], 1, 24),
        "repeat_scale": _number(raw.get("repeat_scale"), default["repeat_scale"], 0.05, 2.0),
        "repeat_rotation": _number(raw.get("repeat_rotation"), default["repeat_rotation"], -360.0, 360.0),
        "segments": _integer(raw.get("segments"), default["segments"], 3, 360),
        "sides": _integer(raw.get("sides"), default["sides"], 3, 24),
        "points": _integer(raw.get("points"), default["points"], 3, 24),
        "inner_ratio": _number(raw.get("inner_ratio"), default["inner_ratio"], 0.05, 0.95),
        "aspect": _number(raw.get("aspect"), default["aspect"], 0.1, 3.0),
        "arm_width": _number(raw.get("arm_width"), default["arm_width"], 0.05, 0.95),
        "turns": _number(raw.get("turns"), default["turns"], 0.25, 12.0),
        "cycles": _number(raw.get("cycles"), default["cycles"], 0.25, 12.0),
        "amplitude": _number(raw.get("amplitude"), default["amplitude"], 0.0, 1.0),
    }


def normalize_shape_layers(raw_layers):
    layers = [normalize_shape_layer(raw, index) for index, raw in enumerate(raw_layers or [])]
    if not any(layer["enabled"] for layer in layers):
        raise ValueError("Shape Field needs at least one enabled shape layer")
    return layers
```

- [ ] **Step 4: Implement all seven primitive builders**

Add `primitive(layer, radius)` using these exact rules:

```python
def _polar(radius, angle):
    return radius * math.cos(angle), radius * math.sin(angle)


def primitive(layer, radius):
    kind = layer["type"]
    if kind == "circle":
        count = layer["segments"]
        return [_polar(radius, 2 * math.pi * i / count) for i in range(count + 1)]
    if kind == "polygon":
        count = layer["sides"]
        return [_polar(radius, 2 * math.pi * i / count - math.pi / 2) for i in range(count + 1)]
    if kind == "star":
        count = layer["points"] * 2
        return [
            _polar(radius if i % 2 == 0 else radius * layer["inner_ratio"], math.pi * i / layer["points"] - math.pi / 2)
            for i in range(count + 1)
        ]
    if kind == "diamond":
        aspect = layer["aspect"]
        return [(0.0, -radius), (radius * aspect, 0.0), (0.0, radius), (-radius * aspect, 0.0), (0.0, -radius)]
    if kind == "cross":
        arm = radius * layer["arm_width"]
        return [
            (-arm, -radius), (arm, -radius), (arm, -arm), (radius, -arm),
            (radius, arm), (arm, arm), (arm, radius), (-arm, radius),
            (-arm, arm), (-radius, arm), (-radius, -arm), (-arm, -arm), (-arm, -radius),
        ]
    if kind == "spiral":
        count = layer["segments"]
        return [
            _polar(radius * i / count, 2 * math.pi * layer["turns"] * i / count - math.pi / 2)
            for i in range(count + 1)
        ]
    count = layer["segments"]
    return [
        (
            -radius + 2 * radius * i / count,
            radius * layer["amplitude"] * math.sin(2 * math.pi * layer["cycles"] * i / count),
        )
        for i in range(count + 1)
    ]
```

- [ ] **Step 5: Run Task 1 tests and commit**

Run `uv run python -m pytest tests/test_shape_field.py -v`; expect all current tests to pass.

```powershell
git add engine/shape_field.py tests/test_shape_field.py
git commit -m "feat: add shape field primitives"
```

### Task 2: Lattices, combination modes, repetition, modulation, and randomness

**Files:**
- Modify: `engine/shape_field.py`
- Modify: `tests/test_shape_field.py`

- [ ] **Step 1: Add failing field-generation tests**

Append tests that call `field_points`, `normalize_shape_field_params`, and `shape_field`:

```python
from engine.shape_field import (
    SHAPE_FIELD_PARAMS,
    field_points,
    normalize_shape_field_params,
    shape_field,
)
from engine.params import defaults


class ShapeFieldGenerationTest(unittest.TestCase):
    def params(self):
        params = defaults(SHAPE_FIELD_PARAMS)
        params["shape_layers"] = DEFAULT_SHAPE_LAYERS
        return normalize_shape_field_params(SHAPE_FIELD_PARAMS, params)

    def test_all_layouts_produce_requested_finite_tile_count(self):
        for layout in ("square", "brick", "hex", "triangular", "jittered"):
            with self.subTest(layout=layout):
                params = self.params() | {"layout": layout, "rows": 3, "columns": 4}
                points = field_points(params, random.Random(7))
                self.assertEqual(len(points), 12)
                self.assertTrue(all(math.isfinite(point["x"]) and math.isfinite(point["y"]) for point in points))

    def test_modes_produce_distinct_non_empty_geometry(self):
        outputs = {}
        for mode in ("nested", "alternating", "connected", "overlapping"):
            params = self.params() | {"combination_mode": mode, "rows": 2, "columns": 3}
            lines, _, _ = shape_field(params, seed=9)
            self.assertTrue(lines)
            outputs[mode] = lines
        self.assertEqual(len({repr(lines) for lines in outputs.values()}), 4)

    def test_repeats_modulation_and_randomness_are_deterministic(self):
        params = self.params()
        params.update({
            "rows": 3,
            "columns": 3,
            "modulation_source": "wave",
            "modulation_target": "combined",
            "modulation_amount": 0.7,
            "position_jitter": 0.15,
            "rotation_jitter": 25.0,
            "scale_jitter": 0.2,
        })
        params["shape_layers"] = [{**DEFAULT_SHAPE_LAYERS[0], "repeat_count": 3}]
        first = shape_field(params, seed=42)[0]
        second = shape_field(params, seed=42)[0]
        changed = shape_field(params, seed=43)[0]
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)

    def test_output_budget_fails_before_large_geometry_is_built(self):
        params = self.params() | {"rows": 60, "columns": 60}
        params["shape_layers"] = [{**DEFAULT_SHAPE_LAYERS[0], "repeat_count": 24}] * 2
        with self.assertRaisesRegex(ValueError, "50,000"):
            shape_field(params, seed=0)
```

- [ ] **Step 2: Verify tests fail because field generation is absent**

Run `uv run python -m pytest tests/test_shape_field.py::ShapeFieldGenerationTest -v`; expect import failures for the new functions.

- [ ] **Step 3: Add scalar schema and validation**

Define `SHAPE_FIELD_PARAMS` with exact names used by the UI and tests:

```python
SHAPE_FIELD_PARAMS = [
    Param("layout", "enum", "square", group="Field", choices=["square", "brick", "hex", "triangular", "jittered"]),
    Param("combination_mode", "enum", "nested", group="Field", choices=["nested", "alternating", "connected", "overlapping"]),
    Param("rows", "int", 7, group="Field", min=1, max=60),
    Param("columns", "int", 5, group="Field", min=1, max=60),
    Param("spacing", "float", 4.2, group="Field", min=0.2, max=40, help="cm"),
    Param("field_rotation", "angle", 0.0, group="Field", min=-180, max=180),
    Param("field_offset_x", "float", 0.0, group="Field", min=-60, max=60, help="cm"),
    Param("field_offset_y", "float", 0.0, group="Field", min=-60, max=60, help="cm"),
    Param("layout_jitter", "float", 0.25, group="Field", min=0, max=1),
    Param("modulation_source", "enum", "none", group="Evolution", choices=["none", "row", "column", "radial", "wave", "noise"]),
    Param("modulation_target", "enum", "scale", group="Evolution", choices=["scale", "rotation", "offset", "combined"]),
    Param("modulation_amount", "float", 0.0, group="Evolution", min=0, max=2),
    Param("modulation_frequency", "float", 1.0, group="Evolution", min=0.05, max=12),
    Param("modulation_phase", "angle", 0.0, group="Evolution", min=-360, max=360),
    Param("position_jitter", "float", 0.0, group="Random", min=0, max=1),
    Param("rotation_jitter", "float", 0.0, group="Random", min=0, max=180),
    Param("scale_jitter", "float", 0.0, group="Random", min=0, max=1),
    Param("drop_probability", "float", 0.0, group="Random", min=0, max=0.95),
    Param("seed", "int", 0, group="Random"),
]


def normalize_shape_field_params(schema, values):
    normalized = validate(schema, values)
    normalized["shape_layers"] = normalize_shape_layers((values or {}).get("shape_layers", DEFAULT_SHAPE_LAYERS))
    return normalized
```

- [ ] **Step 4: Implement the field pipeline**

Implement these focused functions in `engine/shape_field.py`:

```python
def field_points(params, rng):
    rows, columns = params["rows"], params["columns"]
    spacing, layout = params["spacing"], params["layout"]
    raw = []
    for row in range(rows):
        for column in range(columns):
            if layout == "brick":
                x, y = (column + 0.5 * (row % 2)) * spacing, row * spacing
            elif layout == "hex":
                x = column * spacing * 1.5
                y = (row + 0.5 * (column % 2)) * spacing * math.sqrt(3)
            elif layout == "triangular":
                x = (column + 0.5 * (row % 2)) * spacing
                y = row * spacing * math.sqrt(3) / 2
            else:
                x, y = column * spacing, row * spacing
            if layout == "jittered":
                amount = params["layout_jitter"] * spacing
                x += rng.uniform(-amount, amount)
                y += rng.uniform(-amount, amount)
            raw.append({"row": row, "column": column, "index": len(raw), "x": x, "y": y})

    center_x = (min(tile["x"] for tile in raw) + max(tile["x"] for tile in raw)) / 2
    center_y = (min(tile["y"] for tile in raw) + max(tile["y"] for tile in raw)) / 2
    target_x = float(params.get("page_width", 29.7)) / 2 + params["field_offset_x"]
    target_y = float(params.get("page_height", 42.0)) / 2 + params["field_offset_y"]
    angle = math.radians(params["field_rotation"])
    cosine, sine = math.cos(angle), math.sin(angle)
    for tile in raw:
        x, y = tile["x"] - center_x, tile["y"] - center_y
        tile["x"] = target_x + x * cosine - y * sine
        tile["y"] = target_y + x * sine + y * cosine
    return raw

def modulation_value(params, tile, max_radius, seed):
    source = params["modulation_source"]
    if source == "none":
        return 0.0
    if source == "row":
        return -1.0 + 2.0 * tile["row"] / max(1, params["rows"] - 1)
    if source == "column":
        return -1.0 + 2.0 * tile["column"] / max(1, params["columns"] - 1)
    center_x = float(params.get("page_width", 29.7)) / 2 + params["field_offset_x"]
    center_y = float(params.get("page_height", 42.0)) / 2 + params["field_offset_y"]
    if source == "radial":
        distance = math.hypot(tile["x"] - center_x, tile["y"] - center_y)
        return -1.0 + 2.0 * distance / max(max_radius, 1e-9)
    if source == "noise":
        return random.Random((seed + 1) * 1_000_003 + tile["index"]).uniform(-1.0, 1.0)
    phase = math.radians(params["modulation_phase"])
    progress = tile["index"] / max(1, params["rows"] * params["columns"] - 1)
    return math.sin(2 * math.pi * params["modulation_frequency"] * progress + phase)

def transform_line(line, scale, rotation, x, y):
    angle = math.radians(rotation)
    cosine, sine = math.cos(angle), math.sin(angle)
    return [
        (x + scale * px * cosine - scale * py * sine,
         y + scale * px * sine + scale * py * cosine)
        for px, py in line
    ]

def estimate_polylines(params, tile_count):
    layers = [layer for layer in params["shape_layers"] if layer["enabled"]]
    if params["combination_mode"] == "alternating":
        per_tile = max(layer["repeat_count"] for layer in layers)
    else:
        per_tile = sum(layer["repeat_count"] for layer in layers)
    estimate = tile_count * per_tile
    if params["combination_mode"] == "connected":
        estimate += tile_count * 3
    if estimate > 50_000:
        raise ValueError(
            f"Shape Field would emit about {estimate:,} polylines (limit 50,000); "
            "reduce rows, columns, layers, or repeats"
        )
    return estimate

def shape_field(params, seed=0):
    layers = normalize_shape_layers(params.get("shape_layers", DEFAULT_SHAPE_LAYERS))
    params = {**params, "shape_layers": layers}
    rng = random.Random(seed)
    tiles = field_points(params, rng)
    estimate_polylines(params, len(tiles))
    spacing = params["spacing"]
    page_width = float(params.get("page_width", 29.7))
    page_height = float(params.get("page_height", 42.0))
    center_x = page_width / 2 + params["field_offset_x"]
    center_y = page_height / 2 + params["field_offset_y"]
    max_radius = max(math.hypot(tile["x"] - center_x, tile["y"] - center_y) for tile in tiles)
    lines = []
    kept = {}
    enabled = [layer for layer in layers if layer["enabled"]]

    for tile in tiles:
        if rng.random() < params["drop_probability"]:
            continue
        x = tile["x"] + rng.uniform(-1, 1) * params["position_jitter"] * spacing
        y = tile["y"] + rng.uniform(-1, 1) * params["position_jitter"] * spacing
        rotation = rng.uniform(-1, 1) * params["rotation_jitter"]
        scale = max(0.0, 1.0 + rng.uniform(-1, 1) * params["scale_jitter"])
        mod = modulation_value(params, tile, max_radius, seed)
        amount, target = params["modulation_amount"], params["modulation_target"]
        if target in {"scale", "combined"}:
            scale *= max(0.0, 1.0 + 0.5 * amount * mod)
        if target in {"rotation", "combined"}:
            rotation += 180.0 * amount * mod
        if target in {"offset", "combined"}:
            x += 0.5 * spacing * amount * mod
            y -= 0.5 * spacing * amount * mod
        kept[(tile["row"], tile["column"])] = (x, y)

        selected = [enabled[tile["index"] % len(enabled)]] if params["combination_mode"] == "alternating" else enabled
        for layer_index, layer in enumerate(selected):
            layer_x = x + layer["offset_x"] * spacing
            layer_y = y + layer["offset_y"] * spacing
            if params["combination_mode"] == "overlapping" and layer_index:
                angle = 2 * math.pi * (layer_index - 1) / max(1, len(selected) - 1)
                layer_x += 0.5 * spacing * math.cos(angle)
                layer_y += 0.5 * spacing * math.sin(angle)
            for repeat in range(layer["repeat_count"]):
                radius = 0.5 * spacing * layer["scale"] * scale * layer["repeat_scale"] ** repeat
                if radius <= 1e-9:
                    continue
                base = primitive(layer, radius)
                lines.append(transform_line(base, 1.0, layer["rotation"] + rotation + layer["repeat_rotation"] * repeat, layer_x, layer_y))

    if params["combination_mode"] == "connected":
        directions = [(0, 1), (1, 0)]
        if params["layout"] in {"hex", "triangular"}:
            directions.append((1, 1))
        for (row, column), start in kept.items():
            for row_delta, column_delta in directions:
                end = kept.get((row + row_delta, column + column_delta))
                if end is not None:
                    lines.append([start, end])
    return lines, page_width, page_height
```

Use `radius = spacing * 0.5 * layer["scale"] * tile_scale`, multiply by `repeat_scale ** repeat_index`, add `repeat_rotation * repeat_index`, and convert layer offsets from cell units by multiplying them by spacing. In overlapping mode, add a half-spacing radial offset to every layer after the first. Skip zero-radius output.

- [ ] **Step 5: Run all backend module tests and commit**

Run `uv run python -m pytest tests/test_shape_field.py -v`; expect all tests to pass.

```powershell
git add engine/shape_field.py tests/test_shape_field.py
git commit -m "feat: generate modulated shape fields"
```

### Task 3: Register Shape Field and expose additive API metadata

**Files:**
- Modify: `engine/generate.py`
- Modify: `web/server.py`
- Modify: `tests/test_shape_field.py`

- [ ] **Step 1: Write failing registry and API tests**

Add tests asserting:

```python
from engine.generate import get_generator, list_generators
import web.server as server


class ShapeFieldRegistryTest(unittest.TestCase):
    def test_shape_field_is_selectable_with_editor_metadata(self):
        self.assertIn({"id": "shape_field", "name": "Shape Field"}, list_generators())
        generator = get_generator("shape_field")
        self.assertEqual(generator["editor"], "shape_field")
        self.assertEqual(generator["shape_types"], list(SHAPE_TYPES))
        self.assertEqual(len(generator["defaults"]["shape_layers"]), 3)

    def test_schema_endpoint_exposes_dedicated_editor_contract(self):
        client = server.app.test_client()
        payload = client.get("/api/generate/shape_field/schema").get_json()
        self.assertEqual(payload["editor"], "shape_field")
        self.assertEqual(payload["shape_types"], list(SHAPE_TYPES))
        self.assertEqual(len(payload["defaults"]["shape_layers"]), 3)
```

- [ ] **Step 2: Verify registry tests fail**

Run `uv run python -m pytest tests/test_shape_field.py::ShapeFieldRegistryTest -v`; expect `Unknown generator 'shape_field'` or missing list entries.

- [ ] **Step 3: Register the generator and normalizer**

Import Shape Field symbols into `engine/generate.py`, rename `_PAGE_PARAMS` to `PAGE_PARAMS`, keep the Spokes schema using it, and register:

```python
_SHAPE_FIELD_ALL_PARAMS = SHAPE_FIELD_PARAMS + PAGE_PARAMS + FRAMEWORK_PARAMS

GENERATORS["shape_field"] = {
    "id": "shape_field",
    "name": "Shape Field",
    "editor": "shape_field",
    "params": _SHAPE_FIELD_ALL_PARAMS,
    "defaults": {"shape_layers": deepcopy(DEFAULT_SHAPE_LAYERS)},
    "shape_types": list(SHAPE_TYPES),
    "normalize": lambda values: normalize_shape_field_params(_SHAPE_FIELD_ALL_PARAMS, values),
    "fn": shape_field,
}
```

In `_generate_worker`, replace generic validation with:

```python
        normalizer = gen.get("normalize")
        vals = normalizer(params) if normalizer else validate(gen["params"], params)
```

In the schema endpoint, build an additive response:

```python
    payload = {"id": g["id"], "name": g["name"], "params": schema_json(g["params"])}
    for key in ("editor", "defaults", "shape_types"):
        if key in g:
            payload[key] = g[key]
    return jsonify(payload)
```

- [ ] **Step 4: Run registry/API tests and commit**

Run `uv run python -m pytest tests/test_shape_field.py tests/test_generate_crop.py -v`; expect all tests to pass.

```powershell
git add engine/generate.py web/server.py tests/test_shape_field.py
git commit -m "feat: register shape field generator"
```

### Task 4: Add frontend metadata and structured parameter state

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/state.svelte.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `tests/test_frontend_contracts.py`

- [ ] **Step 1: Write failing frontend contract assertions**

Add this test to `tests/test_frontend_contracts.py`:

```python
    def test_shape_field_frontend_state_contract(self):
        types = (ROOT / "frontend/src/lib/types.ts").read_text(encoding="utf-8")
        state = (ROOT / "frontend/src/lib/state.svelte.ts").read_text(encoding="utf-8")
        api = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
        self.assertIn("export interface ShapeLayerT", types)
        self.assertIn("generatorEditor = $state<string | null>(null)", state)
        self.assertIn("generatorDefaults = $state<Record<string, any>>({})", state)
        self.assertIn("generatorShapeTypes = $state<string[]>([])", state)
        self.assertIn("studio.generatorEditor = sch.editor ?? null", api)
        self.assertIn("studio.generatorDefaults = structuredClone(sch.defaults ?? {})", api)
        self.assertIn("studio.generatorShapeTypes = sch.shape_types ?? []", api)
        self.assertIn("keep.shape_layers = structuredClone", api)
        self.assertIn("async restoreGeneratorLayer", api)
        self.assertIn("await this.restoreGeneratorLayer(studio.selectedLayer)", api)
```

Run `uv run python -m pytest tests/test_frontend_contracts.py -q`; expect failure on the first missing contract.

- [ ] **Step 2: Add the TypeScript shape-layer contract**

Define in `types.ts`:

```typescript
export interface ShapeLayerT {
  id: string;
  enabled: boolean;
  type: "circle" | "polygon" | "star" | "diamond" | "cross" | "spiral" | "wave";
  scale: number;
  rotation: number;
  offset_x: number;
  offset_y: number;
  repeat_count: number;
  repeat_scale: number;
  repeat_rotation: number;
  segments: number;
  sides: number;
  points: number;
  inner_ratio: number;
  aspect: number;
  arm_width: number;
  turns: number;
  cycles: number;
  amplitude: number;
}
```

- [ ] **Step 3: Store and load generator editor metadata**

Add to `PlotterForge`:

```typescript
  generatorEditor = $state<string | null>(null);
  generatorDefaults = $state<Record<string, any>>({});
  generatorShapeTypes = $state<string[]>([]);
```

Update `api.selectGenerator` after fetching the schema:

```typescript
    studio.generatorEditor = sch.editor ?? null;
    studio.generatorDefaults = structuredClone(sch.defaults ?? {});
    studio.generatorShapeTypes = sch.shape_types ?? [];
    const keep: Record<string, any> = {};
    for (const p of sch.params) keep[p.name] = studio.genParams[p.name] ?? p.default;
    if (studio.generatorEditor === "shape_field") {
      keep.shape_layers = structuredClone(
        Array.isArray(studio.genParams.shape_layers)
          ? studio.genParams.shape_layers
          : studio.generatorDefaults.shape_layers ?? [],
      );
    }
    studio.genParams = keep;
```

Add a single restoration helper and call it after selecting a target generator layer, during boot when the selected composition layer is generated, and from `loadVersion` instead of its duplicated restoration block:

```typescript
  async restoreGeneratorLayer(layer: CompositionLayerT | null | undefined) {
    if (layer?.kind !== "generate" || !layer.source?.generator_id) return false;
    const previousAutoRedraw = studio.autoRedraw;
    studio.autoRedraw = false;
    try {
      if (!await this.selectGenerator(layer.source.generator_id)) return false;
      studio.genParams = {
        ...studio.genParams,
        ...structuredClone(layer.source.params ?? {}),
      };
      return true;
    } finally {
      studio.autoRedraw = previousAutoRedraw;
    }
  },
```

Change `selectLayer` to await `patchLayer` and then call `restoreGeneratorLayer(studio.selectedLayer)`. In `boot`, after the initial `selectGenerator`, restore the selected generated layer. Replace the existing manual generator restoration in `loadVersion` with the same helper. This makes project, target-layer, and version restoration use one path.

- [ ] **Step 4: Run checks and commit**

Run `uv run python -m pytest tests/test_frontend_contracts.py -q` and `npm run check` from `frontend`; expect both to pass.

```powershell
git add frontend/src/lib/types.ts frontend/src/lib/state.svelte.ts frontend/src/lib/api.ts tests/test_frontend_contracts.py
git commit -m "feat: track shape field editor state"
```

### Task 5: Build the dedicated Shape Field editor

**Files:**
- Create: `frontend/src/components/generate/ShapeFieldEditor.svelte`
- Modify: `frontend/src/components/panels/GeneratePanel.svelte`
- Modify: `tests/test_frontend_contracts.py`

- [ ] **Step 1: Add failing editor wiring assertions**

Add this test to `tests/test_frontend_contracts.py`:

```python
    def test_shape_field_dedicated_editor_contract(self):
        panel = (ROOT / "frontend/src/components/panels/GeneratePanel.svelte").read_text(encoding="utf-8")
        editor_path = ROOT / "frontend/src/components/generate/ShapeFieldEditor.svelte"
        self.assertIn('import ShapeFieldEditor from "../generate/ShapeFieldEditor.svelte"', panel)
        self.assertIn('studio.generatorEditor === "shape_field"', panel)
        self.assertIn("<ShapeFieldEditor", panel)
        self.assertTrue(editor_path.exists())
        editor = editor_path.read_text(encoding="utf-8")
        for operation in ("setLayers", "patchLayer", "addLayer", "duplicateLayer", "removeLayer", "moveLayer"):
            self.assertIn(f"function {operation}", editor)
        self.assertIn("shape_layers: layers", editor)
        self.assertIn('class="shape-field-editor"', editor)
        self.assertIn('class="shape-card"', editor)
        self.assertIn('aria-label="Add shape"', editor)
        for shape_type in ("polygon", "star", "diamond", "cross", "spiral", "wave"):
            self.assertIn(f'layer.type === "{shape_type}"', editor)
```

Run the focused frontend contract test; expect failure because the component is not created yet.

- [ ] **Step 2: Implement immutable layer operations**

In the new component, derive `layers` from `studio.genParams.shape_layers` and implement:

```typescript
function setLayers(layers: ShapeLayerT[]) {
  studio.genParams = { ...studio.genParams, shape_layers: layers };
}

function patchLayer(id: string, patch: Partial<ShapeLayerT>) {
  setLayers(layers.map((layer) => layer.id === id ? { ...layer, ...patch } : layer));
}

function addLayer() {
  const source = structuredClone(studio.generatorDefaults.shape_layers?.[0]);
  setLayers([...layers, { ...source, id: crypto.randomUUID() }]);
}

function duplicateLayer(id: string) {
  const index = layers.findIndex((layer) => layer.id === id);
  if (index < 0) return;
  const copy = { ...structuredClone(layers[index]), id: crypto.randomUUID() };
  setLayers([...layers.slice(0, index + 1), copy, ...layers.slice(index + 1)]);
}

function removeLayer(id: string) {
  setLayers(layers.filter((layer) => layer.id !== id));
}

function moveLayer(id: string, direction: number) {
  const index = layers.findIndex((layer) => layer.id === id);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= layers.length) return;
  const next = [...layers];
  [next[index], next[target]] = [next[target], next[index]];
  setLayers(next);
}
```

- [ ] **Step 3: Render the dedicated editor**

Render four sections. Reuse `ParamControl` for the scalar `studio.genSchema` groups. In Shape Stack, render each layer as a card with:

- enable checkbox and type select from `studio.generatorShapeTypes`;
- common numeric inputs for scale, rotation, offsets, repeat count/scale/rotation;
- conditional inputs: segments for circle/spiral/wave, sides for polygon, points + inner ratio for star, aspect for diamond, arm width for cross, turns for spiral, cycles + amplitude for wave;
- Up, Down, Duplicate, and Remove buttons;
- an Add Shape button with accessible name `Add shape`.

Every input calls `patchLayer` with a parsed number and has a stable accessible label containing the layer index and property name. Add component-scoped card, header, action, and compact numeric-grid styling.

In `GeneratePanel.svelte`:

```svelte
<script lang="ts">
  import ShapeFieldEditor from "../generate/ShapeFieldEditor.svelte";
  // existing imports and logic remain
</script>

{#if studio.generatorEditor === "shape_field"}
  <ShapeFieldEditor />
{:else}
  {#each groups as [group, params] (group)}
    <!-- existing generic groups -->
  {/each}
{/if}
```

- [ ] **Step 4: Run frontend contracts/check/build and commit**

Run:

```powershell
uv run python -m pytest tests/test_frontend_contracts.py -q
Set-Location frontend
npm run check
npm run build
```

Expect zero test failures, zero Svelte errors, and a successful Vite build.

```powershell
git add frontend/src/components/generate/ShapeFieldEditor.svelte frontend/src/components/panels/GeneratePanel.svelte tests/test_frontend_contracts.py
git commit -m "feat: add dedicated shape field editor"
```

### Task 6: Add end-to-end coverage and documentation

**Files:**
- Modify: `frontend/e2e/e-generator.spec.ts`
- Modify: `frontend/e2e/USER_STORIES.md`
- Modify: `FEATURES.md`

- [ ] **Step 1: Add the failing Shape Field journey**

Append an E8 test that:

```typescript
test("E8: Shape Field dedicated editor builds and persists a dynamic pattern", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E E8 Shape Field");
  await gotoApp(page);
  await page.getByRole("button", { name: "ï¼‹ Generator" }).click();
  await page.locator(".gen-select").selectOption("shape_field");
  await expect(page.locator(".shape-field-editor")).toBeVisible();
  await page.getByRole("button", { name: "Add shape" }).click();
  await expect(page.locator(".shape-card")).toHaveCount(4);
  await page.getByRole("button", { name: "âœ¦ Generate", exact: true }).click();
  const composition = await waitForGeneratedLayer(request, baseURL!);
  const layer = composition.layers[0];
  expect(layer.svg).toMatch(DRAWING_SHAPE);
  expect(layer.source.generator_id).toBe("shape_field");
  expect(layer.source.params.shape_layers).toHaveLength(4);
});
```

- [ ] **Step 2: Run the E8 test and fix only observable integration defects**

Run `npm run e2e -- e-generator.spec.ts -g "E8"` from `frontend`; expect one passing test.

- [ ] **Step 3: Update feature inventories**

Add a `FEATURES.md` generator bullet describing Shape Field's dynamic layers, five layouts, four modes, modulation, and seeded randomness. Add E8 to `USER_STORIES.md` and update its coverage totals by one story and one test.

- [ ] **Step 4: Commit integration coverage**

```powershell
git add frontend/e2e/e-generator.spec.ts frontend/e2e/USER_STORIES.md FEATURES.md
git commit -m "test: cover shape field generator journey"
```

### Task 7: Full verification

**Files:**
- Verify all files above.

- [ ] **Step 1: Run backend verification**

Run `uv run python -m pytest -q`; expect all tests to pass.

- [ ] **Step 2: Run frontend static verification**

From `frontend`, run `npm run check` and `npm run build`; expect zero errors and successful build.

- [ ] **Step 3: Run the complete generator E2E spec**

From `frontend`, run `npm run e2e -- e-generator.spec.ts`; expect all generator stories, including E8, to pass.

- [ ] **Step 4: Inspect repository state**

Run `git diff --check`, `git status --short`, and `git log -8 --oneline`; expect no formatting errors, no uncommitted files, and the planned commits on `codex/shape-pattern-generator`.
