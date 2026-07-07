"""Endpoint welding + Euler-trail chaining (engine.chain)."""

import math
import unittest

from engine.chain import _chain_point_lists, chain_items, chain_polylines
from engine.geometry import Dot, Geometry, Item


def _length(pts):
    return sum(
        math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        for i in range(len(pts) - 1)
    )


class ChainPointListsTest(unittest.TestCase):
    def test_square_becomes_one_circuit(self):
        segs = [[(0, 0), (1, 0)], [(1, 0), (1, 1)], [(1, 1), (0, 1)], [(0, 1), (0, 0)]]
        merged, _ = _chain_point_lists(segs, 0.0)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0]), 5)  # closed circuit, first point repeated

    def test_star_with_2k_odd_nodes_gives_k_trails(self):
        # 4 spokes from origin: 4 odd leaf nodes + centre (even, deg 4) -> 2 trails
        segs = [[(0, 0), (1, 0)], [(0, 0), (-1, 0)], [(0, 0), (0, 1)], [(0, 0), (0, -1)]]
        merged, _ = _chain_point_lists(segs, 0.0)
        self.assertEqual(len(merged), 2)

    def test_point_conservation_and_length(self):
        # total drawn length must be preserved exactly at tol=0, and every
        # original edge id must be used exactly once across the trails.
        segs = [
            [(0, 0), (1, 0)], [(1, 0), (1, 1)], [(1, 1), (0, 1)], [(0, 1), (0, 0)],
            [(2, 2), (3, 2)], [(3, 2), (3, 3)],
        ]
        total_before = sum(_length(s) for s in segs)
        merged, trail_edges = _chain_point_lists(segs, 0.0)
        total_after = sum(_length(m) for m in merged)
        self.assertAlmostEqual(total_before, total_after, places=9)
        all_eids = sorted(e for eids in trail_edges for e in eids)
        self.assertEqual(all_eids, list(range(len(segs))))

    def test_tolerance_weld(self):
        segs = [[(0, 0), (1, 0)], [(1.03, 0), (2, 0)]]
        self.assertEqual(len(_chain_point_lists(segs, 0.05)[0]), 1)
        self.assertEqual(len(_chain_point_lists(segs, 0.0)[0]), 2)


class ChainItemsTest(unittest.TestCase):
    def test_closed_and_dot_items_pass_through(self):
        dot_item = Item(lum=0.5, dot=Dot(1, 1, 0.3))
        closed_item = Item(lum=0.4, path=Geometry([(0, 0), (1, 0), (1, 1), (0, 0)], closed=True))
        open_a = Item(lum=0.5, path=Geometry([(0, 0), (1, 0)]))
        open_b = Item(lum=0.5, path=Geometry([(1, 0), (1, 1)]))

        out = chain_items([dot_item, closed_item, open_a, open_b])

        # dot + closed pass through untouched; the two open items merge to one
        self.assertEqual(len(out), 3)
        self.assertIn(dot_item, out)
        self.assertIn(closed_item, out)
        merged = next(it for it in out if it not in (dot_item, closed_item))
        self.assertEqual(merged.path.points, [(0, 0), (1, 0), (1, 1)])
        # length-weighted mean of lums (equal lengths and lums here -> 0.5)
        self.assertAlmostEqual(merged.lum, 0.5, places=9)

    def test_single_open_item_is_left_alone(self):
        # fewer than 2 open items -> chain_items returns the input untouched
        only = [Item(lum=0.5, path=Geometry([(0, 0), (1, 0)]))]
        out = chain_items(only)
        self.assertEqual(out, only)

    def test_triangulation_merges(self):
        from PIL import Image

        from engine.pfm.base import generate_items, get

        img = Image.new("L", (120, 120))
        px = img.load()
        for y in range(120):
            for x in range(120):
                px[x, y] = int(255 * (x / 119.0))  # gradient -> plenty of dark pixels
        pfm = get("voronoi_triangulation")
        base_values = {"seed": 1, "triangulate_corners": False}

        unmerged = generate_items(pfm, img, {**base_values, "merge_strokes": False}, 1, (120, 120))
        merged = generate_items(pfm, img, {**base_values, "merge_strokes": True}, 1, (120, 120))

        self.assertGreater(len(unmerged), 20)
        # path count must be far below edge count
        self.assertLess(len(merged), len(unmerged) / 2)

        def total_len(items):
            total = 0.0
            for it in items:
                if it.path is not None:
                    total += _length(it.path.points)
            return total

        self.assertAlmostEqual(total_len(unmerged), total_len(merged), places=6)


class ChainPolylinesTest(unittest.TestCase):
    def test_tolerance_zero_is_a_noop(self):
        polylines = [[(0, 0), (1, 0)], [(1, 0), (1, 1)]]
        out = chain_polylines(polylines, 0.0)
        self.assertEqual(out, polylines)

    def test_merges_touching_open_polylines(self):
        polylines = [[(0, 0), (1, 0)], [(1.0, 0.0), (1, 1)]]
        out = chain_polylines(polylines, 0.1)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0], [(0, 0), (1, 0), (1, 1)])

    def test_closed_polyline_passes_through(self):
        closed = [(0, 0), (1, 0), (1, 1), (0, 0)]
        polylines = [closed, [(5, 5), (6, 5)], [(6, 5), (6, 6)]]
        out = chain_polylines(polylines, 0.1)
        self.assertIn(closed, out)
        self.assertEqual(len(out), 2)  # closed passthrough + 1 merged trail

    def test_arcpath_passes_through(self):
        class ArcPath(list):
            arc = {"cx": 0, "cy": 0, "r": 1}

        arc = ArcPath([(0, 0), (1, 1)])
        polylines = [arc, [(5, 5), (6, 5)], [(6, 5), (6, 6)]]
        out = chain_polylines(polylines, 0.1)
        self.assertIn(arc, out)
        self.assertEqual(len(out), 2)


if __name__ == "__main__":
    unittest.main()
