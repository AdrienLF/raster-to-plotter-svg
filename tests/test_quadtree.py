"""Quadtree Mosaic PFM (engine.pfm.quadtree)."""

import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from engine.pfm import quadtree
from engine.pfm.base import REGISTRY, generate_items, get


def _image(arr):
    return Image.fromarray(arr.astype(np.uint8), "L").convert("RGB")


def _leaves(img, values):
    """Run only the subdivision by monkeypatching the cell renderer away."""
    rects = []

    def spy(pfm, work, overrides, seed, bounds, *a, **k):
        rects.append((bounds, overrides))
        return []

    with patch.object(quadtree, "generate_items", side_effect=spy):
        generate_items(get("quadtree_mosaic"), img, values, 1, img.size)
    return rects


class QuadtreeTest(unittest.TestCase):
    def test_registered(self):
        self.assertIn("quadtree_mosaic", REGISTRY)

    def test_uniform_image_single_leaf(self):
        img = _image(np.full((256, 256), 90))
        rects = _leaves(img, {"seed": 1, "detail": 60, "padding": 0})
        self.assertEqual(len(rects), 1)

    def test_checkerboard_splits(self):
        tile = np.kron([[0, 1], [1, 0]], np.ones((64, 64))) * 255
        img = _image(np.tile(tile, (2, 2)))
        rects = _leaves(img, {"seed": 1, "detail": 100, "padding": 0,
                              "max_depth": 5})
        self.assertGreater(len(rects), 4)

    def test_leaf_cap(self):
        rng = np.random.default_rng(0)
        img = _image(rng.integers(0, 255, (512, 512)))
        rects = _leaves(img, {"seed": 1, "detail": 100, "max_depth": 8,
                              "min_cell_px": 8, "padding": 0})
        self.assertLessEqual(len(rects), quadtree.MAX_LEAVES)

    def test_density_override_tracks_tone(self):
        arr = np.full((256, 256), 250)
        arr[:, :128] = 5                      # dark left half
        img = _image(arr)
        captured = []

        def spy(pfm, work, overrides, seed, bounds, *a, **k):
            captured.append((pfm.id, overrides))
            return []

        with patch.object(quadtree, "generate_items", side_effect=spy):
            generate_items(get("quadtree_mosaic"), img,
                           {"seed": 1, "detail": 80,
                            "style_dark": "voronoi_stippling",
                            "style_light": "voronoi_stippling"},
                           1, (256, 256))
        densities = [o["point_density"] for pid, o in captured
                     if pid == "voronoi_stippling"]
        self.assertTrue(densities)
        self.assertGreater(max(densities), min(densities))

    def test_geometry_within_bounds(self):
        arr = np.tile(np.linspace(0, 255, 256), (256, 1))
        img = _image(arr)
        items = generate_items(get("quadtree_mosaic"), img,
                               {"seed": 2, "style_dark": "grid_halftone",
                                "style_light": "grid_halftone",
                                "draw_outlines": True},
                               2, (256, 256))
        self.assertTrue(items)
        for it in items:
            if it.dot is not None:
                self.assertTrue(-1 <= it.dot.x <= 257 and -1 <= it.dot.y <= 257)
            if it.path is not None:
                for (x, y) in it.path.points:
                    self.assertTrue(-1 <= x <= 257 and -1 <= y <= 257)


if __name__ == "__main__":
    unittest.main()
