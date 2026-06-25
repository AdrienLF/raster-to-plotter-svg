import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendContractsTest(unittest.TestCase):
    def test_svg_upload_does_not_trigger_plot_estimate(self):
        api_ts = (ROOT / "frontend/src/lib/api.ts").read_text()
        match = re.search(
            r"async uploadSvg\(file: File\) \{(?P<body>.*?)\n  \},",
            api_ts,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        self.assertNotIn("refreshEstimate", match.group("body"))

    def test_export_menu_uses_visible_layers_not_stats(self):
        menu = (ROOT / "frontend/src/components/MenuBar.svelte").read_text()

        self.assertIn("disabled={!studio.hasVisibleLayers}", menu)
        self.assertNotIn("disabled={!studio.stats}", menu)

    def test_composition_layer_bounds_toggle_is_visible_in_viewport(self):
        state = (ROOT / "frontend/src/lib/state.svelte.ts").read_text()
        panel = (ROOT / "frontend/src/components/panels/CompositionPanel.svelte").read_text()
        viewport = (ROOT / "frontend/src/components/Viewport.svelte").read_text()

        self.assertIn("showLayerBounds", state)
        self.assertIn("bind:checked={studio.showLayerBounds}", panel)
        self.assertIn('class:show-bounds={studio.step === "composition" || studio.showLayerBounds}', viewport)
        self.assertIn(".art.show-bounds", viewport)

    def test_composition_layer_movement_is_not_clamped_to_page(self):
        viewport = (ROOT / "frontend/src/components/Viewport.svelte").read_text()
        placement = (ROOT / "frontend/src/lib/placement.ts").read_text()

        self.assertIn("clamp = true", placement)
        self.assertIn("snapPlacement(raw, drawingSize, page, A4_PORTRAIT, 4, false)", viewport)
        # align passes the visible (anchor-offset) position and clamp=false.
        self.assertIn("{ x: layer.x + off.x, y: layer.y + off.y }", viewport)
        self.assertIn("alignPlacement(", viewport)
        self.assertNotIn("clampPlacement", viewport)


if __name__ == "__main__":
    unittest.main()
