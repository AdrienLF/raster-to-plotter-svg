"""Greedy nearest-neighbour reorder must match the naive O(n^2) tour exactly.

The fast (vectorised / GPU) path replaced a plain python loop used for pen-path
ordering; if the tour diverges, plot travel time and the estimate drift.
Run: python -m unittest tests.test_reorder
"""

import random
import unittest

from engine import accel


def _naive_order(starts, ends):
    """Reference: the original greedy loop, on indices."""
    n = len(starts)
    remaining = list(range(1, n))
    order = [0]
    last = ends[0]
    while remaining:
        best = min(remaining, key=lambda i: (starts[i][0] - last[0]) ** 2
                   + (starts[i][1] - last[1]) ** 2)
        order.append(best)
        remaining.remove(best)
        last = ends[best]
    return order


class ReorderEquivalenceTest(unittest.TestCase):
    def _case(self, n, seed):
        rng = random.Random(seed)
        polys = [[(rng.random() * 420, rng.random() * 297),
                  (rng.random() * 420, rng.random() * 297)] for _ in range(n)]
        starts = [p[0] for p in polys]
        ends = [p[-1] for p in polys]
        self.assertEqual(accel.greedy_nearest_order(starts, ends),
                         _naive_order(starts, ends))

    def test_matches_naive(self):
        for n in (1, 2, 5, 50, 300):
            for seed in (0, 1, 2):
                self._case(n, seed)


if __name__ == "__main__":
    unittest.main()
