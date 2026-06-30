"""Spokes & Circles per-pen distribution: bucket tagging through the pipeline."""

import unittest

from engine import svg_io
from engine.generate import cull_inside_polygon, get_generator, spokes_and_circles
from engine.genframe import _clip_lines
from engine.pens import Pen


def _params(**over):
    p = {pm.name: pm.default for pm in get_generator("spokes_and_circles")["params"]}
    # Isolate the circles so tag positions are easy to assert.
    p.update(spokes=3, circles=2, rays=0, draw_spokes=False, draw_crop_radius=False)
    p.update(over)
    return p


class SpokesPenBuckets(unittest.TestCase):
    def test_cycle_off_stays_three_tuple(self):
        result = spokes_and_circles(_params(pen_cycle=False))
        self.assertEqual(len(result), 3)  # backward-compatible single-pen contract
        self.assertTrue(result[0])

    def test_per_cluster_tags_one_bucket_per_spoke(self):
        lines, _, _, pens = spokes_and_circles(_params(pen_cycle=True, pen_circles="per_cluster"))
        self.assertEqual(len(pens), len(lines))
        # 3 spokes x 2 rings, ordered spoke-major: [0,0, 1,1, 2,2]
        self.assertEqual(pens, [0, 0, 1, 1, 2, 2])

    def test_per_ring_tags_line_up_across_spokes(self):
        _, _, _, pens = spokes_and_circles(_params(pen_cycle=True, pen_circles="per_ring"))
        self.assertEqual(pens, [0, 1, 0, 1, 0, 1])

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

    def test_reverse_and_offset(self):
        _, _, _, pens = spokes_and_circles(
            _params(pen_cycle=True, pen_circles="per_cluster", pen_order="reverse", pen_offset=5)
        )
        # offset + (-1)*s  ->  spoke 0,1,2 -> 5,4,3
        self.assertEqual(pens, [5, 5, 4, 4, 3, 3])

    def test_circles_off_uses_first_pen(self):
        _, _, _, pens = spokes_and_circles(_params(pen_cycle=True, pen_circles="off"))
        self.assertEqual(pens, [None] * 6)

    def test_rays_and_border_have_their_own_pen_buckets(self):
        _, _, _, pens = spokes_and_circles(_params(
            pen_cycle=True, pen_circles="off", draw_spokes=False,
            rays=8, crop_radius=0.1,                # tiny crop so rays survive
            pen_rays=2, draw_crop_radius=True, pen_border=3,
        ))
        non_none = {t for t in pens if t is not None}
        self.assertIn(2, non_none)   # rays -> pen_rays
        self.assertIn(3, non_none)   # crop/border outline -> pen_border


class TagThreading(unittest.TestCase):
    def test_clip_lines_duplicates_tag_across_split(self):
        # seg_fn keeps two non-contiguous pieces -> one input line becomes two.
        def seg(a, b):
            q1 = (a[0] + (b[0] - a[0]) * 0.25, a[1], 0.0)
            q3 = (a[0] + (b[0] - a[0]) * 0.75, a[1], 0.0)
            return [(a, q1), (q3, b)]

        lines = [[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)]]
        out, tags = _clip_lines(lines, seg, tags=[7])
        self.assertEqual(len(out), 2)
        self.assertEqual(tags, [7, 7])

    def test_cull_preserves_tag_for_outside_line(self):
        line = [(0.0, 0.0), (1.0, 0.0)]
        poly = [(100.0, 100.0), (101.0, 100.0), (101.0, 101.0), (100.0, 101.0), (100.0, 100.0)]
        out, tags = cull_inside_polygon([line], poly, tags=[3])
        self.assertTrue(out)
        self.assertTrue(all(t == 3 for t in tags))
        self.assertEqual(len(out), len(tags))


class MultiPenSvg(unittest.TestCase):
    def test_one_group_per_nonempty_pen_with_colours(self):
        pens = [Pen(name="A", colour="#aa0000"), Pen(name="B", colour="#00bb00"),
                Pen(name="C", colour="#0000cc")]
        pen_lines = [
            (pens[0], [[(0.0, 0.0), (1.0, 1.0)]]),
            (pens[1], []),                            # empty -> skipped
            (pens[2], [[(2.0, 2.0), (3.0, 3.0)]]),
        ]
        svg = svg_io.lines_to_svg_layers(pen_lines, 100.0, 100.0)
        self.assertEqual(svg.count('inkscape:groupmode="layer"'), 2)
        self.assertIn("#aa0000", svg)
        self.assertIn("#0000cc", svg)
        self.assertNotIn("#00bb00", svg)


if __name__ == "__main__":
    unittest.main()
