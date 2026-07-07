"""Plot-level tolerant merge (web.server.svg_to_polylines / _paths_signature)."""

import unittest

import web.server as server

# Two touching open paths sharing the point (10, 0), same shape as the
# composed-page SVGs used in tests/test_multipen_plot.py (100mm page,
# viewBox 0 0 100 100 -> 1 user unit == 1 mm).
TOUCHING_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
    'viewBox="0 0 100 100">'
    '<path d="M0,0 L10,0"/><path d="M10,0 L10,10"/>'
    '</svg>'
).encode()


class SvgToPolylinesMergeTest(unittest.TestCase):
    def test_no_merge_by_default(self):
        settings = {"reordering": "none"}
        polylines = server.svg_to_polylines(TOUCHING_SVG, settings, respect_stop=False)
        self.assertEqual(len(polylines), 2)

    def test_zero_tolerance_is_explicit_noop(self):
        settings = {"reordering": "none", "merge_tolerance_mm": 0}
        polylines = server.svg_to_polylines(TOUCHING_SVG, settings, respect_stop=False)
        self.assertEqual(len(polylines), 2)

    def test_positive_tolerance_merges_touching_paths(self):
        settings = {"reordering": "none", "merge_tolerance_mm": 0.1}
        polylines = server.svg_to_polylines(TOUCHING_SVG, settings, respect_stop=False)
        self.assertEqual(len(polylines), 1)


class PathsSignatureCacheInvalidationTest(unittest.TestCase):
    def test_signature_changes_with_merge_tolerance(self):
        placement = {"x": 0.0, "y": 0.0}
        sig_off = server._paths_signature(TOUCHING_SVG, {"merge_tolerance_mm": 0}, placement)
        sig_on = server._paths_signature(TOUCHING_SVG, {"merge_tolerance_mm": 0.1}, placement)
        self.assertNotEqual(sig_off, sig_on)

    def test_signature_stable_for_same_tolerance(self):
        placement = {"x": 0.0, "y": 0.0}
        sig_a = server._paths_signature(TOUCHING_SVG, {"merge_tolerance_mm": 0.1}, placement)
        sig_b = server._paths_signature(TOUCHING_SVG, {"merge_tolerance_mm": 0.1}, placement)
        self.assertEqual(sig_a, sig_b)


if __name__ == "__main__":
    unittest.main()
