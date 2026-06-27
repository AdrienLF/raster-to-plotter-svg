import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendContractsTest(unittest.TestCase):
    def test_app_boots_before_connecting_event_stream(self):
        app = (ROOT / "frontend/src/App.svelte").read_text(encoding="utf-8")
        match = re.search(
            r"onMount\(\(\) => \{(?P<body>.*?)\n  \}\);",
            app,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("let es: EventSource | null = null", body)
        self.assertRegex(
            body,
            r"void api\.boot\(\)\s*\.then\(\(\) => \{\s*es = connectStream\(\);\s*\}\)\s*\.catch",
        )
        self.assertEqual(body.count("connectStream()"), 1)
        self.assertIn('pushLog("Boot error: "', body)
        self.assertIn('studio.status = "Error"', body)
        self.assertIn("studio.processing = false", body)
        self.assertIn("return () => es?.close()", body)

    def test_switch_project_resets_transient_state_before_boot(self):
        api_ts = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
        match = re.search(
            r"async switchProject\(payload: any\) \{(?P<body>.*?)\n  \},",
            api_ts,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        before_boot, separator, _ = match.group("body").partition("await this.boot();")
        self.assertTrue(separator)
        self.assertIn("this.applyProject(payload)", before_boot)
        for reset in (
            "studio.previewSvg = null",
            "studio.stats = null",
            "studio.plotProgress = null",
            "studio.plotEstimate = null",
            "studio.processing = false",
            "studio.plotting = false",
            "studio.progress = 0",
            'studio.status = "Idle"',
            'studio.step = "composition"',
        ):
            self.assertIn(reset, before_boot)

    def test_svg_upload_does_not_trigger_plot_estimate(self):
        api_ts = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
        match = re.search(
            r"async uploadSvg\(file: File\) \{(?P<body>.*?)\n  \},",
            api_ts,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        self.assertNotIn("refreshEstimate", match.group("body"))

    def test_export_menu_uses_visible_layers_not_stats(self):
        menu = (ROOT / "frontend/src/components/MenuBar.svelte").read_text(encoding="utf-8")

        self.assertIn("disabled={!studio.hasVisibleLayers}", menu)
        self.assertNotIn("disabled={!studio.stats}", menu)

    def test_composition_layer_bounds_toggle_is_visible_in_viewport(self):
        state = (ROOT / "frontend/src/lib/state.svelte.ts").read_text(encoding="utf-8")
        panel = (ROOT / "frontend/src/components/panels/CompositionPanel.svelte").read_text(encoding="utf-8")
        viewport = (ROOT / "frontend/src/components/Viewport.svelte").read_text(encoding="utf-8")

        self.assertIn("showLayerBounds", state)
        self.assertIn("bind:checked={studio.showLayerBounds}", panel)
        self.assertIn('class:show-bounds={studio.step === "composition" || studio.showLayerBounds}', viewport)
        self.assertIn(".art.show-bounds", viewport)

    def test_composition_layer_movement_is_not_clamped_to_page(self):
        viewport = (ROOT / "frontend/src/components/Viewport.svelte").read_text(encoding="utf-8")
        placement = (ROOT / "frontend/src/lib/placement.ts").read_text(encoding="utf-8")

        self.assertIn("clamp = true", placement)
        self.assertIn("snapPlacement(raw, drawingSize, page, A4_PORTRAIT, 4, false)", viewport)
        # align passes the visible (anchor-offset) position and clamp=false.
        self.assertIn("{ x: layer.x + off.x, y: layer.y + off.y }", viewport)
        self.assertIn("alignPlacement(", viewport)
        self.assertNotIn("clampPlacement", viewport)

    def test_region_types_and_state_exist(self):
        types = (ROOT / "frontend/src/lib/types.ts").read_text(encoding="utf-8")
        state = (ROOT / "frontend/src/lib/state.svelte.ts").read_text(encoding="utf-8")

        self.assertIn("export interface RegionT", types)
        self.assertIn("export interface SegmentationPromptT", types)
        self.assertIn("regions = $state<RegionT[]>([])", state)
        self.assertIn("selectedRegionId = $state<string | null>(null)", state)
        self.assertIn("regionDraftMask = $state<string | null>(null)", state)

    def test_process_sends_selected_region_id(self):
        api_ts = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
        match = re.search(
            r"async process\(\) \{(?P<body>.*?)\n  \},",
            api_ts,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        self.assertIn("region_id: studio.selectedRegionId || undefined", match.group("body"))

    def test_path_finding_window_exposes_region_controls(self):
        # Region creation lives in the unified floating Path Finding window now,
        # not a left-dock panel.
        panel = (ROOT / "frontend/src/components/panels/LayerStylePanel.svelte").read_text(encoding="utf-8")

        self.assertIn("Create AI region", panel)
        self.assertIn("Save region", panel)
        self.assertIn("selectedRegionId", panel)
        self.assertIn("invertRegion", panel)

    def test_viewport_supports_source_region_selection(self):
        viewport = (ROOT / "frontend/src/components/Viewport.svelte").read_text(encoding="utf-8")

        self.assertIn("region-select-overlay", viewport)
        self.assertIn("api.predictRegion", viewport)
        self.assertIn("regionDraftMask", viewport)
        self.assertIn("e.button === 2 || e.altKey", viewport)

    def test_layer_style_panel_contract_exists(self):
        app = (ROOT / "frontend/src/App.svelte").read_text(encoding="utf-8")
        panel = (ROOT / "frontend/src/components/panels/LayerStylePanel.svelte").read_text(encoding="utf-8")
        types = (ROOT / "frontend/src/lib/types.ts").read_text(encoding="utf-8")
        state = (ROOT / "frontend/src/lib/state.svelte.ts").read_text(encoding="utf-8")
        api_ts = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")

        self.assertIn("LayerStylePanel", app)
        self.assertIn("layerStyleOpen = $state(false)", state)
        self.assertIn("layerStyleSchema = $state<Param[]>([])", state)
        self.assertIn("display_mode", types)
        self.assertIn("pathfinding_style", types)
        self.assertIn("occlude_below", types)
        self.assertIn("/pathfinding/generate", api_ts)
        self.assertIn("generateLayerPathfinding", api_ts)
        self.assertIn("display_mode", panel)
        self.assertIn("pathfinding_style", panel)
        self.assertIn("occlude_below", panel)

    def test_composition_panel_opens_layer_style_and_toggles_occlusion(self):
        panel = (ROOT / "frontend/src/components/panels/CompositionPanel.svelte").read_text(encoding="utf-8")

        self.assertIn("openLayerStyle", panel)
        self.assertIn("studio.layerStyleOpen = true", panel)
        self.assertIn("occlude_below", panel)

    def test_layers_panel_shows_applied_algorithm(self):
        panel = (ROOT / "frontend/src/components/panels/CompositionPanel.svelte").read_text(encoding="utf-8")

        # The Photoshop-style layers list surfaces which PFM is baked into a layer.
        self.assertIn("appliedAlgo", panel)
        self.assertIn("pathfinding_style", panel)

    def test_layers_panel_is_always_visible(self):
        app = (ROOT / "frontend/src/App.svelte").read_text(encoding="utf-8")

        # Layers panel is rendered outside the per-step branches (not step-gated),
        # and the path-finding controls are no longer a left-dock panel.
        self.assertIn('<Panel title="Layers"><CompositionPanel /></Panel>', app)
        self.assertNotIn("PathFindingPanel", app)

    def test_viewport_renders_live_occlusion(self):
        viewport = (ROOT / "frontend/src/components/Viewport.svelte").read_text(encoding="utf-8")

        # Occlusion is composited live via cheap opaque knockout rects (clipping a
        # huge stippling SVG with clip-path was too slow).
        self.assertIn("occludersForLayer", viewport)
        self.assertIn("knockout", viewport)


if __name__ == "__main__":
    unittest.main()
