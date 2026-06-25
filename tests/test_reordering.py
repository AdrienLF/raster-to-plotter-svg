import unittest

import web.server as server


def travel_distance(polylines):
    pos = (0.0, 0.0)
    total = 0.0
    for poly in polylines:
        total += server._dist(pos, poly[0])
        total += sum(server._dist(poly[i - 1], poly[i]) for i in range(1, len(poly)))
        pos = poly[-1]
    total += server._dist(pos, (0.0, 0.0))
    return total


class ReorderingTest(unittest.TestCase):
    def test_nearest_reversible_flips_path_when_endpoint_is_closer(self):
        polylines = [
            [(0.0, 0.0), (1.0, 0.0)],
            [(20.0, 0.0), (2.0, 0.0)],
        ]

        ordered = server._reorder(polylines, "nearest_reversible")

        self.assertEqual(ordered[1][0], (2.0, 0.0))
        self.assertEqual(ordered[1][-1], (20.0, 0.0))

    def test_two_opt_never_worsens_travel_after_nearest_reversible_seed(self):
        polylines = [
            [(0.0, 0.0), (2.0, 0.0)],
            [(90.0, 0.0), (100.0, 0.0)],
            [(11.0, 0.0), (10.0, 0.0)],
            [(80.0, 0.0), (70.0, 0.0)],
        ]

        seeded = server._reorder(polylines, "nearest_reversible")
        optimized = server._reorder(polylines, "two_opt")

        self.assertLessEqual(travel_distance(optimized), travel_distance(seeded))
        self.assertEqual(sorted(len(p) for p in optimized), sorted(len(p) for p in polylines))

    def test_reordering_mode_accepts_legacy_numbers_and_named_modes(self):
        self.assertEqual(server._reordering_mode({"reordering": 0}), "none")
        self.assertEqual(server._reordering_mode({"reordering": 1}), "nearest")
        self.assertEqual(server._reordering_mode({"reordering": "two_opt"}), "two_opt")
        self.assertEqual(server._reordering_mode({"reordering": "nearest-reversible"}), "nearest_reversible")


if __name__ == "__main__":
    unittest.main()
