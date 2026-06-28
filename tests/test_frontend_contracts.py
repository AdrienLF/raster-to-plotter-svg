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
        self.assertIn("let disposed = false", body)
        self.assertLess(body.index("api.boot()"), body.index("connectStream()"))
        self.assertGreaterEqual(body.count("if (disposed"), 2)
        self.assertEqual(body.count("connectStream()"), 1)
        self.assertIn('pushLog("Boot error: "', body)
        self.assertIn('studio.status = "Error"', body)
        self.assertIn("studio.processing = false", body)
        cleanup = body[body.index("return () =>"):]
        self.assertLess(cleanup.index("disposed = true"), cleanup.index("es?.close()"))
        self.assertIn("api.invalidateProjectWork()", cleanup)
        self.assertLess(cleanup.index("api.invalidateProjectWork()"), cleanup.index("es?.close()"))

    def test_boot_uses_generation_guards_through_sequential_loads(self):
        api_ts = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
        match = re.search(
            r"async boot\((?P<signature>.*?)\) \{(?P<body>.*?)\n  \},\n\n  applyProject",
            api_ts,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        self.assertIn("generation", match.group("signature"))
        body = match.group("body")
        self.assertGreaterEqual(body.count("isCurrentProject(generation)"), 4)
        self.assertIn("this.selectPfm(studio.pfmId, generation)", body)
        self.assertIn("this.selectGenerator(studio.generatorId, generation)", body)
        self.assertIn("this.refreshVersions(generation)", body)
        self.assertIn("return true", body)

    def test_switch_project_resets_transient_state_before_boot(self):
        api_ts = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
        match = re.search(
            r"async switchProject\(payload: any(?P<signature>.*?)\) \{(?P<body>.*?)\n  \},",
            api_ts,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        before_boot, separator, _ = match.group("body").partition("await this.boot(")
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
            "studio.regionDraftMask = null",
            "studio.regionDraftBbox = null",
            "studio.regionPositivePoints = []",
            "studio.regionNegativePoints = []",
            "studio.regionSelecting = false",
            "studio.regionPredicting = false",
            "studio.maskMode = null",
            "studio.maskEdit = false",
            "studio.layerStyleOpen = false",
        ):
            self.assertIn(reset, before_boot)

    def test_project_actions_invalidate_older_async_work_and_report_failures(self):
        api_ts = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")

        self.assertIn("let projectGeneration = 0", api_ts)
        self.assertIn("function beginProjectGeneration()", api_ts)
        self.assertIn("function isCurrentProject(generation: number)", api_ts)
        for method, next_method in (
            ("newProject", "openProject"),
            ("openProject", "renameProject"),
            ("deleteProject", "applyComposition"),
        ):
            match = re.search(
                rf"async {method}\(.*?\) \{{(?P<body>.*?)\n  \}},\n\n  (?:async )?{next_method}",
                api_ts,
                re.DOTALL,
            )
            self.assertIsNotNone(match)
            self.assertIn("beginProjectGeneration()", match.group("body"))
            self.assertIn("reportBootError", match.group("body"))

        switch = re.search(
            r"async switchProject\(.*?\) \{(?P<body>.*?)\n  \},\n\n  async newProject",
            api_ts,
            re.DOTALL,
        )
        self.assertIsNotNone(switch)
        self.assertIn("catch", switch.group("body"))
        self.assertIn("reportBootError", switch.group("body"))
        self.assertNotIn("throw", switch.group("body"))

    def test_region_prediction_drops_results_from_an_old_project(self):
        api_ts = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
        match = re.search(
            r"async predictRegion\(.*?\) \{(?P<body>.*?)\n  \},\n\n  async saveRegion",
            api_ts,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("const generation = projectGeneration", body)
        result_guard = body.index("if (!isCurrentProject(generation)) return null")
        self.assertLess(result_guard, body.index("studio.regionDraftMask = j.mask_png"))
        self.assertIn("if (isCurrentProject(generation))", body[body.index("finally"):])

    def test_svg_upload_does_not_trigger_plot_estimate(self):
        api_ts = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
        match = re.search(
            r"async uploadSvg\(file: File\) \{(?P<body>.*?)\n  \},",
            api_ts,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        self.assertNotIn("refreshEstimate", match.group("body"))

    def test_version_load_applies_composition_snapshot_without_reprocessing(self):
        api_ts = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
        match = re.search(
            r"async loadVersion\(.*?\) \{(?P<body>.*?)\n  \},\n\n  exportUrl",
            api_ts,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("if (j.composition)", body)
        snapshot_branch, separator, legacy_branch = body.partition("else")
        self.assertTrue(separator)
        self.assertIn("this.applyComposition(j)", snapshot_branch)
        self.assertIn("studio.processing = false", snapshot_branch)
        self.assertIn('studio.status = "Ready"', snapshot_branch)
        self.assertIn("studio.stats = null", snapshot_branch)
        self.assertIn("studio.plotEstimate = null", snapshot_branch)
        self.assertIn("studio.plotProgress = null", snapshot_branch)
        self.assertIn("studio.previewSvg = null", snapshot_branch)
        self.assertNotIn("this.process()", snapshot_branch)
        self.assertIn("await this.process()", legacy_branch)
        self.assertIn('pushLog("Loaded version")', body)

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
