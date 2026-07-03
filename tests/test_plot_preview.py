import unittest

from engine.composition import Composition
from engine.pens import DrawingSet, Pen
import web.server as server


SIMPLE_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="10mm" viewBox="0 0 20 10">
  <path d="M0 0 L10 0 L10 10"/>
</svg>"""

# One labelled pen → split has a single entry; the plot (and preview) must fall
# back to the whole composed SVG, not the per-pen split (which would drop any
# unlabelled baked geometry, e.g. a masked cavalry layer).
ONE_PEN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
    'viewBox="0 0 100 100">'
    '<g data-layer-id="L1" transform="translate(0 0)">'
    '<g xmlns:ns0="http://www.inkscape.org/namespaces/inkscape" '
    'ns0:groupmode="layer" ns0:label="Black" fill="none" stroke="#000000">'
    '<path d="M0,0 L10,0"/></g>'
    '<path d="M0,20 L10,20"/>'  # unlabelled (masked-layer style) content
    '</g></svg>'
).encode()

# Same composed 2-pen fixture as test_multipen_plot: Black (2 paths), Blue (1).
TWO_PEN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
    'viewBox="0 0 100 100">'
    '<g data-layer-id="L1" transform="translate(0 0)">'
    '<g xmlns:ns0="http://www.inkscape.org/namespaces/inkscape" '
    'ns0:groupmode="layer" ns0:label="Black" fill="none" stroke="#000000">'
    '<path d="M0,0 L10,0"/><path d="M0,5 L10,5"/></g>'
    '<g xmlns:ns0="http://www.inkscape.org/namespaces/inkscape" '
    'ns0:groupmode="layer" ns0:label="Blue" fill="none" stroke="#0000ff">'
    '<path d="M0,10 L10,10"/></g>'
    '</g></svg>'
).encode()


class PlotPreviewTest(unittest.TestCase):
    def setUp(self):
        self.old_svg = server._current_svg
        self.old_placement = server._placement
        self.old_composition = server._project.composition
        self.old_ds = server._project.drawing_set
        self.old_stop_state = server._stop_event.is_set()
        server._stop_event.clear()
        server._current_svg = SIMPLE_SVG
        server._placement = {"x": 0.0, "y": 0.0}
        server._project.composition = Composition()
        # No enabled pens → single-pen (synthetic) path for SIMPLE_SVG.
        server._project.drawing_set = DrawingSet(pens=[])
        self.client = server.app.test_client()

    def tearDown(self):
        server._current_svg = self.old_svg
        server._placement = self.old_placement
        server._project.composition = self.old_composition
        server._project.drawing_set = self.old_ds
        (server._stop_event.set if self.old_stop_state else server._stop_event.clear)()

    def test_returns_ordered_paths_with_negated_y(self):
        response = self.client.get("/api/plot/preview-paths")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["pens"]), 1)
        pen = payload["pens"][0]
        self.assertEqual(pen["colour"], "#000000")
        # Machine convention: Y negative = down (server negates the SVG y).
        self.assertEqual(pen["paths"], [[0.0, 0.0, 10.0, 0.0, 10.0, -10.0]])

    def test_requires_a_loaded_svg(self):
        server._current_svg = None

        response = self.client.get("/api/plot/preview-paths")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "No SVG loaded")

    def test_ignores_stale_plot_cancellation(self):
        server._stop_event.set()

        response = self.client.get("/api/plot/preview-paths")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()["pens"]), 1)

    def test_single_pen_uses_whole_svg_keeping_unlabelled_paths(self):
        server._current_svg = ONE_PEN_SVG
        server._project.drawing_set = DrawingSet(pens=[Pen(name="Black", colour="#000000")])

        response = self.client.get("/api/plot/preview-paths")

        self.assertEqual(response.status_code, 200)
        pens = response.get_json()["pens"]
        # Not split per pen: one synthetic entry covering the whole drawing,
        # including the unlabelled (masked-style) path the split would drop.
        self.assertEqual(len(pens), 1)
        self.assertEqual(len(pens[0]["paths"]), 2)

    def test_single_pen_fallback_reports_matched_pen(self):
        # SIMPLE_SVG is unlabelled; one enabled pen → matched, whole-SVG plot,
        # but the entry reports the real pen name/colour (not synthetic 'Pen').
        server._project.drawing_set = DrawingSet(pens=[Pen(name="Red", colour="#c0392b")])

        response = self.client.get("/api/plot/preview-paths")

        self.assertEqual(response.status_code, 200)
        pens = response.get_json()["pens"]
        self.assertEqual(len(pens), 1)
        self.assertEqual(pens[0]["name"], "Red")
        self.assertEqual(pens[0]["colour"], "#c0392b")

    def test_unlabelled_two_colour_splits_by_nearest_pen(self):
        server._current_svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<path d="M0,0 L10,0" stroke="#0a0a0a"/>'   # near Black
            '<path d="M0,5 L10,5" stroke="#c81e12"/>'   # near Red
            '</svg>'
        ).encode()
        server._project.drawing_set = DrawingSet(pens=[
            Pen(name="Black", colour="#000000"),
            Pen(name="Red", colour="#c0392b"),
        ])

        response = self.client.get("/api/plot/preview-paths")

        self.assertEqual(response.status_code, 200)
        pens = response.get_json()["pens"]
        self.assertEqual([p["name"] for p in pens], ["Black", "Red"])
        self.assertEqual(len(pens[0]["paths"]), 1)
        self.assertEqual(len(pens[1]["paths"]), 1)

    def test_multipen_splits_in_pen_order(self):
        server._current_svg = TWO_PEN_SVG
        server._project.drawing_set = DrawingSet(pens=[
            Pen(name="Black", colour="#000000"),
            Pen(name="Blue", colour="#0000ff"),
        ])

        response = self.client.get("/api/plot/preview-paths")

        self.assertEqual(response.status_code, 200)
        pens = response.get_json()["pens"]
        self.assertEqual([p["name"] for p in pens], ["Black", "Blue"])
        # Structural: Black has 2 paths, Blue has 1 (matches the drawing).
        self.assertEqual(len(pens[0]["paths"]), 2)
        self.assertEqual(len(pens[1]["paths"]), 1)


if __name__ == "__main__":
    unittest.main()
