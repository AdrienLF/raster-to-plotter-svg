"""Stroke-level hidden-line removal (engine.hlr + composition strokes mode)."""

import re
import unittest

from engine import hlr
from engine.composition import Composition, CompositionLayer, compose_visible_svg


def _svg(paths, w=100, h=100):
    body = "".join(
        f'<path d="{d}" stroke="#000000" stroke-width="{sw}" fill="none"/>'
        for d, sw in paths
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" '
        f'viewBox="0 0 {w} {h}">{body}</svg>'
    )


def _layer_paths(svg, layer_id):
    """Count path elements in one layer's group (raw bodies re-serialized by
    ElementTree carry an ``ns0:`` namespace prefix; baked ones do not)."""
    match = re.search(
        rf'<g data-layer-id="{layer_id}"[^>]*>(.*?)</g>', svg, re.DOTALL
    )
    assert match, f"layer {layer_id} not found in composed svg"
    return len(re.findall(r"<(?:[A-Za-z0-9]+:)?path\b", match.group(1)))


class OccludeStackTest(unittest.TestCase):
    def test_crossing_strokes_gap(self):
        near = {"polylines": [[(50, 0), (50, 100)]], "widths": [1.0], "occludes": True}
        far = {"polylines": [[(0, 50), (100, 50)]], "widths": [0.3], "occludes": False}
        out = hlr.occlude_stack([near, far])
        self.assertEqual(len(out[0]), 1)          # near layer untouched
        pieces = out[1]
        self.assertEqual(len(pieces), 2)          # far stroke split at the crossing
        # gap = stroke width + 2 * gap halo = 1.0 + 0.3 mm, within 20 %
        inner = sorted(
            abs(x - 50.0) for pts, _src in pieces for x in (pts[0][0], pts[-1][0])
        )[:2]
        gap = inner[0] + inner[1]
        self.assertGreater(gap, 1.3 * 0.8)
        self.assertLess(gap, 1.3 * 1.2)

    def test_disjoint_bboxes_pass_through(self):
        near = {"polylines": [[(5, 0), (5, 10)]], "widths": [1.0], "occludes": True}
        far_pts = [(60.0, 50.0), (90.0, 50.0)]
        far = {"polylines": [list(far_pts)], "widths": [0.3], "occludes": False}
        out = hlr.occlude_stack([near, far])
        self.assertEqual(out[1], [(far_pts, 0)])

    def test_empty_near_layer(self):
        near = {"polylines": [], "widths": [], "occludes": True}
        far_pts = [(0.0, 50.0), (100.0, 50.0)]
        far = {"polylines": [list(far_pts)], "widths": [0.3], "occludes": False}
        out = hlr.occlude_stack([near, far])
        self.assertEqual(out[1], [(far_pts, 0)])

    def test_non_occluding_layer_does_not_clip(self):
        near = {"polylines": [[(50, 0), (50, 100)]], "widths": [1.0], "occludes": False}
        far_pts = [(0.0, 50.0), (100.0, 50.0)]
        far = {"polylines": [list(far_pts)], "widths": [0.3], "occludes": False}
        out = hlr.occlude_stack([near, far])
        self.assertEqual(out[1], [(far_pts, 0)])

    def test_src_index_maps_attrs(self):
        near = {"polylines": [[(50, 0), (50, 100)]], "widths": [1.0], "occludes": True}
        far = {
            "polylines": [[(0, 40), (100, 40)], [(0, 50), (100, 50)]],
            "widths": [0.3, 0.3],
            "occludes": False,
        }
        out = hlr.occlude_stack([near, far])
        by_src = {}
        for pts, src in out[1]:
            by_src.setdefault(src, []).append(pts)
        self.assertEqual(len(by_src[0]), 2)   # both strokes cross the occluder
        self.assertEqual(len(by_src[1]), 2)


class StrokesOcclusionComposeTest(unittest.TestCase):
    def test_strokes_mode_clips_lower_layer(self):
        far = CompositionLayer(
            id="far", name="Far", kind="svg",
            svg=_svg([("M0 50 L100 50", 0.3)]),
        )
        near = CompositionLayer(
            id="near", name="Near", kind="svg",
            svg=_svg([("M50 0 L50 100", 1.0)]),
            occlude_below=True, occlusion_mode="strokes",
        )
        comp = Composition(layers=[far, near])   # later in list = nearer
        svg = compose_visible_svg(comp)
        self.assertEqual(_layer_paths(svg, "far"), 2)   # split at the crossing
        self.assertEqual(_layer_paths(svg, "near"), 1)  # occluder untouched

    def test_mask_mode_stack_is_unaffected(self):
        far = CompositionLayer(
            id="far", name="Far", kind="svg",
            svg=_svg([("M0 50 L100 50", 0.3)]),
        )
        near = CompositionLayer(
            id="near", name="Near", kind="svg",
            svg=_svg([("M50 0 L50 100", 1.0)]),
            occlude_below=True, occlusion_mode="mask", occlusion_mask=None,
        )
        comp = Composition(layers=[far, near])
        svg = compose_visible_svg(comp)
        # no occlusion_mask -> mask mode does nothing; far layer stays whole
        self.assertEqual(_layer_paths(svg, "far"), 1)

    def test_occlusion_mode_round_trips(self):
        layer = CompositionLayer(
            id="a", name="A", kind="svg", svg=_svg([("M0 0 L1 1", 0.3)]),
            occlude_below=True, occlusion_mode="strokes",
        )
        again = CompositionLayer.from_dict(layer.to_dict(include_svg=True))
        self.assertEqual(again.occlusion_mode, "strokes")
        legacy = CompositionLayer.from_dict({"id": "b", "name": "B", "kind": "svg"})
        self.assertEqual(legacy.occlusion_mode, "mask")


if __name__ == "__main__":
    unittest.main()
