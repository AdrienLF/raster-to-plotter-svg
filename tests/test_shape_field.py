import math
import random
import unittest

from engine.shape_field import (
    DEFAULT_SHAPE_LAYERS,
    SHAPE_FIELD_PARAMS,
    SHAPE_TYPES,
    field_points,
    normalize_shape_layers,
    normalize_shape_field_params,
    primitive,
    shape_field,
)
from engine.params import defaults
from engine.generate import get_generator, list_generators
from engine.genframe import apply_framework
import web.server as server


class ShapeLayerNormalizationTest(unittest.TestCase):
    def test_defaults_cover_extended_shape_palette(self):
        self.assertEqual(
            SHAPE_TYPES,
            ("circle", "polygon", "star", "diamond", "cross", "spiral", "wave"),
        )
        self.assertEqual(
            [layer["type"] for layer in DEFAULT_SHAPE_LAYERS],
            ["circle", "star", "wave"],
        )

    def test_invalid_values_are_sanitized_and_unknown_keys_are_dropped(self):
        [layer] = normalize_shape_layers(
            [
                {
                    "id": "custom",
                    "enabled": "yes",
                    "type": "bogus",
                    "scale": float("nan"),
                    "sides": 99,
                    "repeat_count": 999,
                    "unknown": "drop me",
                }
            ]
        )
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
                self.assertTrue(
                    all(math.isfinite(value) for point in line for value in point)
                )
                if shape_type in {"circle", "polygon", "star", "diamond", "cross"}:
                    self.assertEqual(line[0], line[-1])
                else:
                    self.assertNotEqual(line[0], line[-1])


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
                self.assertTrue(
                    all(
                        math.isfinite(point["x"]) and math.isfinite(point["y"])
                        for point in points
                    )
                )

    def test_modes_produce_distinct_non_empty_geometry(self):
        outputs = {}
        for mode in ("nested", "alternating", "connected", "overlapping"):
            params = self.params() | {
                "combination_mode": mode,
                "rows": 2,
                "columns": 3,
            }
            lines, _, _ = shape_field(params, seed=9)
            self.assertTrue(lines)
            outputs[mode] = lines
        self.assertEqual(len({repr(lines) for lines in outputs.values()}), 4)

    def test_repeats_modulation_and_randomness_are_deterministic(self):
        params = self.params()
        params.update(
            {
                "rows": 3,
                "columns": 3,
                "modulation_source": "wave",
                "modulation_target": "combined",
                "modulation_amount": 0.7,
                "position_jitter": 0.15,
                "rotation_jitter": 25.0,
                "scale_jitter": 0.2,
            }
        )
        params["shape_layers"] = [
            {**DEFAULT_SHAPE_LAYERS[0], "repeat_count": 3}
        ]

        first = shape_field(params, seed=42)[0]
        second = shape_field(params, seed=42)[0]
        changed = shape_field(params, seed=43)[0]

        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)

    def test_output_budget_fails_before_large_geometry_is_built(self):
        params = self.params() | {"rows": 60, "columns": 60}
        params["shape_layers"] = [
            {**DEFAULT_SHAPE_LAYERS[0], "repeat_count": 24},
            {**DEFAULT_SHAPE_LAYERS[0], "id": "circle-2", "repeat_count": 24},
        ]
        with self.assertRaisesRegex(ValueError, "50,000"):
            shape_field(params, seed=0)


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

    def test_registered_defaults_run_through_shared_framework(self):
        generator = get_generator("shape_field")
        params = generator["normalize"]({})

        lines, width, height = generator["fn"](params, seed=0)
        transformed, extras = apply_framework(lines, width, height, params, seed=0)

        self.assertTrue(lines)
        self.assertTrue(transformed or extras)
        self.assertEqual((width, height), (29.7, 42.0))
