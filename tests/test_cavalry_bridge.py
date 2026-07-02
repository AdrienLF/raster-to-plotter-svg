import unittest
from unittest.mock import patch
from pathlib import Path

from engine.composition import (
    A3_PAGE,
    Composition,
    normalize_svg_to_page,
    parse_svg_size_mm,
)
import web.server as server


# A3-aspect Cavalry-style export: px user units, no physical size.
CAVALRY_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1527.27">
  <path d="M0 0 L1080 0" stroke="#000"/>
</svg>"""

ROOT = Path(__file__).resolve().parents[1]


class CavalryScriptContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = (ROOT / "cavalry/plotter-bridge.js").read_text(encoding="utf-8")

    def test_adds_horizontal_layout_through_supported_ui_api(self):
        self.assertIn("ui.add(row);", self.script)
        self.assertNotIn("ui.addLayout", self.script)

    def test_renders_to_stem_and_posts_the_appended_svg_path(self):
        self.assertIn('var TMP_SVG_STEM = api.getTempFolder() + "/cavalry-live-bridge";', self.script)
        self.assertIn('var TMP_SVG = TMP_SVG_STEM + ".svg";', self.script)
        self.assertIn("api.renderSVGFrame(TMP_SVG_STEM, 100, false);", self.script)
        self.assertIn('client.postFromFile("/api/cavalry", TMP_SVG, "image/svg+xml")', self.script)

    def test_creates_and_activates_portrait_a3_composition(self):
        self.assertIn('var createA3 = new ui.Button("New A3 Composition");', self.script)
        self.assertIn('var compId = api.createComp("A3 Plotter · 10 px/mm");', self.script)
        self.assertIn('api.set(compId, { resolution: [2970, 4200] });', self.script)
        self.assertIn("api.setActiveComp(compId);", self.script)
        self.assertIn("ui.add(createA3);", self.script)
        self.assertIn('status.setText("Could not create A3 composition");', self.script)
        self.assertIn("console.error(e);", self.script)


class NormalizeSvgToPageTest(unittest.TestCase):
    def test_px_viewbox_fits_a3_page(self):
        out = normalize_svg_to_page(CAVALRY_SVG, A3_PAGE)
        w, h = parse_svg_size_mm(out)
        self.assertAlmostEqual(w, 297.0, places=1)
        self.assertAlmostEqual(h, 420.0, places=1)
        self.assertIn('transform="scale(0.275)"', out)

    def test_width_height_fallback_when_no_viewbox(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="594" height="840"><path d="M0 0 L1 1"/></svg>'
        out = normalize_svg_to_page(svg, A3_PAGE)
        w, h = parse_svg_size_mm(out)
        self.assertAlmostEqual(w, 297.0, places=1)
        self.assertAlmostEqual(h, 420.0, places=1)
        self.assertIn('scale(0.5)', out)

    def test_non_page_aspect_letterboxes(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M0 0 L1 1"/></svg>'
        out = normalize_svg_to_page(svg, A3_PAGE)
        w, h = parse_svg_size_mm(out)
        self.assertAlmostEqual(w, 297.0, places=1)
        self.assertAlmostEqual(h, 297.0, places=1)


class FakeProject:
    def __init__(self):
        self.composition = Composition()

    def save_composition_layers(self):
        pass


class CavalryBridgeTest(unittest.TestCase):
    def setUp(self):
        self.old_project = server._project
        server._project = FakeProject()
        server._cavalry_pending = None
        server._cavalry_dismissed = None
        self.client = server.app.test_client()

    def tearDown(self):
        server._project = self.old_project
        server._cavalry_pending = None
        server._cavalry_dismissed = None

    @property
    def comp(self):
        return server._project.composition

    def post(self, body=CAVALRY_SVG, session="aaa"):
        return self.client.post("/api/cavalry", data=body,
                                content_type="image/svg+xml",
                                headers={"X-Cavalry-Session": session})

    def decide(self, action):
        return self.client.post("/api/cavalry/session", json={"action": action})

    def add_layer_via_button(self):
        return self.client.post("/api/composition/cavalry-layer")

    # ── input validation ──────────────────────────────────────────────────────
    def test_rejects_non_svg_body(self):
        r = self.client.post("/api/cavalry", data="not an svg")
        self.assertEqual(r.status_code, 400)

    def test_rejects_malformed_xml(self):
        r = self.client.post("/api/cavalry", data="<svg><path")
        self.assertEqual(r.status_code, 400)

    # ── capture flow ──────────────────────────────────────────────────────────
    def test_post_without_capture_layer_parks_frame(self):
        r = self.post()
        self.assertEqual(r.status_code, 202)
        self.assertEqual(len(self.comp.layers), 0)
        self.assertEqual(server._cavalry_pending["session"], "aaa")

    def test_new_decision_creates_live_layer_then_captures(self):
        self.post()
        r = self.decide("new")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.comp.layers), 1)
        layer = self.comp.layers[0]
        self.assertEqual(layer.source,
                         {"bridge": "cavalry", "live": True, "session": "aaa"})
        self.assertIsNone(server._cavalry_pending)
        # Same session now flows straight in.
        r2 = self.post(CAVALRY_SVG.replace("L1080 0", "L540 0"))
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(len(self.comp.layers), 1)
        self.assertIn("L540 0", layer.svg)

    def test_button_arms_layer_that_adopts_first_session(self):
        r = self.add_layer_via_button()
        self.assertEqual(r.status_code, 200)
        layer = self.comp.layers[0]
        self.assertTrue(layer.source["live"])
        self.assertIsNone(layer.source["session"])
        r2 = self.post(session="xyz")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(layer.source["session"], "xyz")
        self.assertEqual(len(self.comp.layers), 1)

    def test_button_binds_parked_frame_immediately(self):
        self.post(session="held")
        self.add_layer_via_button()
        layer = self.comp.layers[0]
        self.assertEqual(layer.source["session"], "held")
        self.assertIn("L1080 0", layer.svg)
        self.assertIsNone(server._cavalry_pending)

    # ── reconnect ─────────────────────────────────────────────────────────────
    def _capture_layer(self, session="aaa"):
        self.add_layer_via_button()
        self.post(session=session)
        return self.comp.layers[0]

    def test_live_frames_preserve_user_crop_and_mask(self):
        # A live capture the user has masked must stay masked across frames — even
        # when normalize_svg_to_page nudges the layer size (letterbox of a changing
        # viewBox). Clearing it wiped the mask every frame, so the plot ran
        # unmasked while a preview snapped in the masked window looked correct.
        layer = self._capture_layer("aaa")
        layer.mask = {"type": "rect", "x": 0, "y": 0, "width": 50, "height": 100}
        layer.crop = {"x": 1, "y": 2, "width": 10, "height": 20}
        # Next frame with a different aspect → different normalized size.
        r = self.post(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<path d="M0 0 L100 0" stroke="#000"/></svg>',
            session="aaa",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(layer.mask, {"type": "rect", "x": 0, "y": 0, "width": 50, "height": 100})
        self.assertEqual(layer.crop, {"x": 1, "y": 2, "width": 10, "height": 20})

    def test_new_session_prompts_instead_of_overwriting(self):
        layer = self._capture_layer("aaa")
        old_svg = layer.svg
        r = self.post(CAVALRY_SVG.replace("L1080 0", "L1 0"), session="bbb")
        self.assertEqual(r.status_code, 202)
        self.assertEqual(layer.svg, old_svg)

    def test_continue_rebinds_and_preserves_placement(self):
        layer = self._capture_layer("aaa")
        layer.x, layer.y, layer.scale = 10.0, 20.0, 0.5
        self.post(CAVALRY_SVG.replace("L1080 0", "L2 0"), session="bbb")
        r = self.decide("continue")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.comp.layers), 1)
        self.assertEqual(layer.source["session"], "bbb")
        self.assertTrue(layer.source["live"])
        self.assertIn("L2 0", layer.svg)
        self.assertEqual((layer.x, layer.y, layer.scale), (10.0, 20.0, 0.5))

    def test_new_after_reconnect_freezes_old_layer(self):
        old = self._capture_layer("aaa")
        self.post(session="bbb")
        self.decide("new")
        self.assertEqual(len(self.comp.layers), 2)
        self.assertFalse(old.source["live"])
        new = self.comp.layers[1]
        self.assertTrue(new.source["live"])
        self.assertEqual(new.source["session"], "bbb")
        # Old capture kept its content; new session posts land on the new layer.
        r = self.post(CAVALRY_SVG.replace("L1080 0", "L3 0"), session="bbb")
        self.assertEqual(r.status_code, 200)
        self.assertIn("L3 0", new.svg)
        self.assertNotIn("L3 0", old.svg)

    def test_dismiss_silences_session(self):
        self._capture_layer("aaa")
        self.post(session="bbb")
        r = self.decide("dismiss")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(server._cavalry_pending)
        self.assertEqual(server._cavalry_dismissed, "bbb")
        # Further posts from bbb still park but keep quiet.
        r2 = self.post(session="bbb")
        self.assertEqual(r2.status_code, 202)

    def test_decision_without_pending_is_conflict(self):
        r = self.decide("new")
        self.assertEqual(r.status_code, 409)

    def test_unknown_action_rejected(self):
        self.post()
        r = self.decide("bogus")
        self.assertEqual(r.status_code, 400)

    def test_project_switch_forgets_dismissed_session(self):
        self._capture_layer("aaa")
        self.post(session="bbb")
        self.decide("dismiss")
        self.assertEqual(server._cavalry_dismissed, "bbb")

        replacement = FakeProject()
        with patch.object(server, "get_or_create", return_value=replacement):
            server._switch_project("another-project")

        self.assertIsNone(server._cavalry_pending)
        self.assertIsNone(server._cavalry_dismissed)


if __name__ == "__main__":
    unittest.main()
