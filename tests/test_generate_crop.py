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
