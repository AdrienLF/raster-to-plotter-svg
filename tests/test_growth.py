"""Differential growth (engine.growth)."""

import time
import unittest

import numpy as np
from PIL import Image

from engine.pfm.base import REGISTRY, generate_items, get
from engine.growth import MAX_NODES


def _image(arr):
    return Image.fromarray(arr.astype(np.uint8), "L").convert("RGB")


def _all_points(items):
    pts = []
    for it in items:
        if it.path is not None:
            pts.extend(it.path.points)
    return pts


class GrowthTest(unittest.TestCase):
    def test_registered(self):
        self.assertIn("differential_growth", REGISTRY)

    def test_deterministic_per_seed(self):
        img = _image(np.full((150, 150), 40))
        params = {"seed": 4, "seed_count": 4, "iterations": 60}
        a = generate_items(get("differential_growth"), img, params, 4, (150, 150))
        b = generate_items(get("differential_growth"), img, params, 4, (150, 150))
        self.assertEqual([it.path.points for it in a],
                         [it.path.points for it in b])

    def test_budget_bounds_and_stability_on_black(self):
        img = _image(np.zeros((300, 300)))
        t0 = time.time()
        items = generate_items(get("differential_growth"), img,
                               {"seed": 1, "seed_count": 8, "iterations": 100},
                               1, (300, 300))
        self.assertLess(time.time() - t0, 60.0)
        pts = _all_points(items)
        self.assertGreater(len(pts), 0)
        self.assertLessEqual(len(pts), MAX_NODES)
        arr = np.asarray(pts, dtype=np.float64)
        self.assertTrue(np.isfinite(arr).all(), "growth produced NaN/inf")
        self.assertTrue((arr[:, 0] >= 0).all() and (arr[:, 0] <= 299).all())
        self.assertTrue((arr[:, 1] >= 0).all() and (arr[:, 1] <= 299).all())
        for it in items:
            self.assertGreaterEqual(len(it.path.points), 3)

    def test_curves_grow(self):
        # After enough iterations a loop must have subdivided far beyond its
        # 6-node hexagon seed.
        img = _image(np.zeros((200, 200)))
        items = generate_items(get("differential_growth"), img,
                               {"seed": 2, "seed_count": 2, "iterations": 120},
                               2, (200, 200))
        self.assertTrue(any(len(it.path.points) > 30 for it in items))

    def test_darkness_bias(self):
        arr = np.full((200, 200), 245)
        arr[:, :100] = 10                    # left half nearly black
        img = _image(arr)
        items = generate_items(get("differential_growth"), img,
                               {"seed": 3, "seed_count": 10, "iterations": 80},
                               3, (200, 200))
        pts = _all_points(items)
        left = sum(1 for (x, _y) in pts if x < 100)
        right = len(pts) - left
        self.assertGreater(left, max(1, right) * 3)

    def test_open_mode_emits_open_paths(self):
        img = _image(np.zeros((150, 150)))
        items = generate_items(get("differential_growth"), img,
                               {"seed": 5, "seed_count": 3, "iterations": 60,
                                "closed_loops": False},
                               5, (150, 150))
        self.assertTrue(items)
        for it in items:
            self.assertFalse(it.path.closed)


if __name__ == "__main__":
    unittest.main()
