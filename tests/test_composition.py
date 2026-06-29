import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import re

from engine.composition import (
    A3_PAGE,
    Composition,
    CompositionLayer,
    compose_visible_svg,
    effective_bounds,
    layer_svg_zip,
    parse_svg_size_mm,
    replace_selected_layer,
)
from engine.geometry import clip_polyline_polygon, point_in_polygon
import web.server as server


LAYER_A = """<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm" viewBox="0 0 210 297">
  <path d="M0 0 L10 0"/>
</svg>"""

LAYER_B = """<svg xmlns="http://www.w3.org/2000/svg" width="120mm" height="80mm" viewBox="0 0 120 80">
  <path d="M5 5 L20 5"/>
</svg>"""


class CompositionTest(unittest.TestCase):
    def test_parse_svg_size_mm_reads_cm_mm_and_viewbox_fallback(self):
        self.assertEqual(
            parse_svg_size_mm('<svg width="21cm" height="297mm"></svg>'),
            (210.0, 297.0),
        )
        self.assertEqual(
            parse_svg_size_mm('<svg viewBox="0 0 120 80"></svg>'),
            (120.0, 80.0),
        )

    def test_replace_selected_layer_creates_a4_layer_at_a3_top_left(self):
        comp = Composition()

        layer = replace_selected_layer(
            comp,
            LAYER_A,
            name="A4 generator",
            kind="generate",
            source={"id": "spokes"},
        )

        self.assertEqual(comp.page, A3_PAGE)
        self.assertEqual(comp.selected_layer_id, layer.id)
        self.assertEqual(layer.x, 0.0)
        self.assertEqual(layer.y, 0.0)
        self.assertEqual(layer.width, 210.0)
        self.assertEqual(layer.height, 297.0)
        self.assertEqual(layer.kind, "generate")

    def test_replace_selected_layer_updates_only_selected_layer(self):
        comp = Composition()
        first = replace_selected_layer(
            comp,
            LAYER_A,
            name="First",
            kind="generate",
            source={"id": "a"},
        )
        second = comp.add_layer(LAYER_B, name="Second", kind="svg", source={"id": "b"})
        comp.selected_layer_id = first.id

        updated = replace_selected_layer(
            comp,
            LAYER_B,
            name="Updated",
            kind="pathfinding",
            source={"id": "pfm"},
        )

        self.assertEqual(updated.id, first.id)
        self.assertEqual(comp.layers[0].name, "Updated")
        self.assertEqual(comp.layers[0].kind, "pathfinding")
        self.assertEqual(comp.layers[0].width, 120.0)
        self.assertEqual(comp.layers[1].id, second.id)
        self.assertEqual(comp.layers[1].name, "Second")

    def test_compose_visible_svg_is_a3_and_excludes_hidden_layers(self):
        comp = Composition()
        a = comp.add_layer(LAYER_A, name="A", kind="generate", source={})
        b = comp.add_layer(LAYER_B, name="B", kind="svg", source={})
        a.x = 12.5
        a.y = 7.0
        b.visible = False

        svg = compose_visible_svg(comp)

        self.assertIn('width="297mm"', svg)
        self.assertIn('height="420mm"', svg)
        self.assertIn('viewBox="0 0 297 420"', svg)
        self.assertIn('data-layer-id="' + a.id + '"', svg)
        self.assertIn('transform="translate(12.5 7)"', svg)
        self.assertNotIn('data-layer-id="' + b.id + '"', svg)

    def test_layer_zip_exports_each_visible_layer_at_own_bounds_with_manifest(self):
        comp = Composition()
        a = comp.add_layer(LAYER_A, name="A4 Layer", kind="generate", source={})
        b = comp.add_layer(LAYER_B, name="Small Layer", kind="svg", source={})
        a.x = 10
        a.y = 20
        b.visible = False

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "layers.zip"
            path.write_bytes(layer_svg_zip(comp))
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                self.assertIn("manifest.json", names)
                self.assertEqual(
                    [n for n in names if n.endswith(".svg")],
                    ["00_A4_Layer.svg"],
                )
                layer_svg = zf.read("00_A4_Layer.svg").decode()
                manifest = json.loads(zf.read("manifest.json").decode())

        self.assertIn('width="210mm"', layer_svg)
        self.assertIn('height="297mm"', layer_svg)
        self.assertEqual(manifest["page"], A3_PAGE)
        self.assertEqual(manifest["layers"][0]["x"], 10)
        self.assertEqual(manifest["layers"][0]["y"], 20)

    def test_compose_visible_svg_reports_progress_per_visible_layer(self):
        comp = Composition()
        comp.add_layer(LAYER_A, name="A", kind="svg", source={})
        comp.add_layer(LAYER_B, name="B", kind="svg", source={})
        hidden = comp.add_layer(LAYER_B, name="Hidden", kind="svg", source={})
        hidden.visible = False

        calls = []
        compose_visible_svg(comp, on_progress=lambda done, total: calls.append((done, total)))

        # Two visible layers: a tick before each (0, 1) then a final completion (2).
        self.assertEqual(calls, [(0, 2), (1, 2), (2, 2)])

    def test_layer_svg_zip_reports_progress_per_visible_layer(self):
        comp = Composition()
        comp.add_layer(LAYER_A, name="A", kind="svg", source={})
        comp.add_layer(LAYER_B, name="B", kind="svg", source={})

        calls = []
        layer_svg_zip(comp, on_progress=lambda done, total: calls.append((done, total)))

        self.assertEqual(calls, [(0, 2), (1, 2), (2, 2)])

    def test_compose_visible_svg_aborts_when_on_progress_raises(self):
        comp = Composition()
        comp.add_layer(LAYER_A, name="A", kind="svg", source={})
        comp.add_layer(LAYER_B, name="B", kind="svg", source={})

        def cancel_after_first(done, total):
            if done >= 1:
                raise RuntimeError("__stopped__")

        with self.assertRaisesRegex(RuntimeError, "__stopped__"):
            compose_visible_svg(comp, on_progress=cancel_after_first)

    def test_layer_actions_reorder_duplicate_and_delete(self):
        comp = Composition()
        a = comp.add_layer(LAYER_A, "A", "svg", {})
        b = comp.add_layer(LAYER_B, "B", "svg", {})

        self.assertTrue(comp.move_layer(b.id, -1))
        self.assertEqual([layer.id for layer in comp.layers], [b.id, a.id])

        copy = comp.duplicate_layer(b.id)

        self.assertIsNotNone(copy)
        self.assertEqual(copy.name, "B copy")
        self.assertNotEqual(copy.id, b.id)
        self.assertEqual(comp.selected_layer_id, copy.id)

        self.assertTrue(comp.delete_layer(b.id))
        self.assertNotIn(b.id, [layer.id for layer in comp.layers])
        self.assertEqual(comp.selected_layer_id, copy.id)


LAYER_BOX = """<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">
  <rect x="20" y="30" width="40" height="25" fill="none" stroke="black"/>
</svg>"""

LAYER_LINE = """<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">
  <path d="M0 50 L100 50" stroke="black"/>
</svg>"""


def _path_ds(svg_body: str) -> list[str]:
    return re.findall(r'<path d="([^"]+)"', svg_body)


class CropMaskTest(unittest.TestCase):
    def test_clip_polyline_polygon_handles_concave_shape(self):
        # A "C" shape with a notch on the right; a horizontal line at y=5 enters
        # the notch and should be cut into the solid part only.
        poly = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 7), (7, 7), (7, 3), (0, 3)]
        self.assertTrue(point_in_polygon((1, 1), poly))
        self.assertFalse(point_in_polygon((3, 5), poly))
        clipped = clip_polyline_polygon([(-1, 5), (11, 5)], poly)
        self.assertEqual(clipped, [[(7.0, 5.0), (10.0, 5.0)]])

    def test_effective_bounds_offsets_by_crop(self):
        layer = CompositionLayer(id="a", name="t", kind="svg", width=100, height=100, svg=LAYER_BOX)
        layer.x, layer.y = 5, 8
        layer.crop = {"x": 20, "y": 30, "width": 40, "height": 25}
        self.assertEqual(
            effective_bounds(layer),
            {"x": 25, "y": 38, "width": 40, "height": 25},
        )

    def test_crop_and_mask_roundtrip_through_dict(self):
        layer = CompositionLayer(id="a", name="t", kind="svg", width=100, height=100, svg=LAYER_BOX)
        layer.crop = {"x": 1, "y": 2, "width": 3, "height": 4}
        layer.mask = {"type": "path", "d": "M 0 0 L 10 0 L 5 10 Z"}
        restored = CompositionLayer.from_dict(layer.to_dict(include_svg=True))
        self.assertEqual(restored.crop, layer.crop)
        self.assertEqual(restored.mask, layer.mask)

    def test_smart_region_layer_fields_roundtrip_through_dict(self):
        layer = CompositionLayer(id="a", name="Face", kind="pathfinding", width=100, height=100, svg=LAYER_BOX)
        layer.region_id = "region-face"
        layer.display_mode = "both"
        layer.occlude_below = True
        layer.occlusion_mask = {"type": "rect", "x": 20, "y": 10, "width": 40, "height": 50}
        layer.pathfinding_style = {
            "enabled": True,
            "pfm_id": "adaptive_stippling",
            "params": {"density": 0.5},
            "status": "stale",
            "cache": {"generated_at": "2026-06-25T10:00:00Z"},
        }

        restored = CompositionLayer.from_dict(layer.to_dict(include_svg=True))

        self.assertEqual(restored.region_id, "region-face")
        self.assertEqual(restored.display_mode, "both")
        self.assertTrue(restored.occlude_below)
        self.assertEqual(restored.occlusion_mask, layer.occlusion_mask)
        self.assertEqual(restored.pathfinding_style, layer.pathfinding_style)

    def test_replace_clears_existing_crop_and_mask(self):
        comp = Composition()
        layer = comp.add_layer(LAYER_BOX, "A", "svg", {})
        layer.crop = {"x": 1, "y": 2, "width": 3, "height": 4}
        layer.mask = {"type": "rect", "x": 0, "y": 0, "width": 5, "height": 5}
        replace_selected_layer(comp, LAYER_LINE, name="A", kind="svg", source={})
        self.assertIsNone(comp.layers[0].crop)
        self.assertIsNone(comp.layers[0].mask)

    def test_rect_mask_bakes_clipped_geometry(self):
        comp = Composition()
        layer = comp.add_layer(LAYER_LINE, "L", "svg", {})
        layer.mask = {"type": "rect", "x": 25, "y": 0, "width": 50, "height": 100}
        svg = compose_visible_svg(comp)
        ds = _path_ds(svg)
        # The horizontal line at y=50 survives only within x ∈ [25, 75].
        self.assertEqual(ds, ["M25 50 L75 50"])

    def test_unclipped_layer_stays_raw(self):
        comp = Composition()
        comp.add_layer(LAYER_LINE, "L", "svg", {})
        svg = compose_visible_svg(comp)
        self.assertIn("M0 50 L100 50", svg)

    def test_layer_name_with_special_chars_produces_valid_xml(self):
        # Names like "Spokes & Circles" must not break the composed SVG.
        from xml.etree import ElementTree as ET

        comp = Composition()
        comp.add_layer(LAYER_LINE, 'Spokes & Circles <"q">', "generate", {})
        svg = compose_visible_svg(comp)
        ET.fromstring(svg.encode("utf-8"))  # raises if not well-formed
        self.assertIn("Spokes &amp; Circles", svg)

    def test_occluding_layer_clips_visible_lower_geometry(self):
        comp = Composition()
        lower = comp.add_layer(LAYER_LINE, "Background paths", "pathfinding", {})
        upper = comp.add_layer(LAYER_BOX, "Face region", "pathfinding", {})
        upper.occlude_below = True
        upper.occlusion_mask = {"type": "rect", "x": 25, "y": 0, "width": 50, "height": 100}

        svg = compose_visible_svg(comp)
        lower_group = re.search(
            rf'data-layer-id="{lower.id}".*?</g>',
            svg,
            flags=re.DOTALL,
        ).group(0)
        ds = _path_ds(lower_group)

        self.assertEqual(ds, ["M0 50 L25 50", "M75 50 L100 50"])


if __name__ == "__main__":
    unittest.main()


class CompositionApiTest(unittest.TestCase):
    def setUp(self):
        self.old_project = server._project
        self.old_svg = server._current_svg
        self.old_placement = server._placement

        class TempProject:
            def __init__(self):
                self.composition = Composition()
                self.drawing_set = server.DrawingSet()
                self.area = server.DrawingArea()
                self.pfm_id = "voronoi_stippling"
                self.params = {}

            def save_composition_layers(self):
                pass

            def save(self):
                pass

        server._project = TempProject()
        server._current_svg = None
        server._placement = {"x": 0.0, "y": 0.0}
        self.client = server.app.test_client()

    def tearDown(self):
        server._project = self.old_project
        server._current_svg = self.old_svg
        server._placement = self.old_placement

    def test_upload_svg_creates_composition_layer(self):
        response = self.client.post(
            "/api/upload",
            data={"file": (io.BytesIO(LAYER_A.encode()), "art.svg")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(len(payload["composition"]["layers"]), 1)
        self.assertEqual(payload["composition"]["layers"][0]["width"], 210.0)
        self.assertNotIn("svg", payload)

    def test_layer_visibility_controls_export(self):
        a = server._project.composition.add_layer(LAYER_A, "A", "svg", {})
        b = server._project.composition.add_layer(LAYER_B, "B", "svg", {})
        b.visible = False

        response = self.client.get("/api/export")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn(a.id, body)
        self.assertNotIn(b.id, body)

    def test_crop_to_content_sets_crop_to_geometry_bounds(self):
        layer = server._project.composition.add_layer(LAYER_BOX, "Box", "svg", {})

        response = self.client.post(f"/api/composition/layers/{layer.id}/crop-to-content")

        self.assertEqual(response.status_code, 200)
        crop = response.get_json()["composition"]["layers"][0]["crop"]
        self.assertAlmostEqual(crop["x"], 20, delta=0.5)
        self.assertAlmostEqual(crop["y"], 30, delta=0.5)
        self.assertAlmostEqual(crop["width"], 40, delta=0.5)
        self.assertAlmostEqual(crop["height"], 25, delta=0.5)

    def test_patch_sets_and_clears_mask(self):
        layer = server._project.composition.add_layer(LAYER_BOX, "Box", "svg", {})

        set_resp = self.client.patch(
            f"/api/composition/layers/{layer.id}",
            json={"mask": {"type": "ellipse", "cx": 50, "cy": 50, "rx": 20, "ry": 10}},
        )
        self.assertEqual(set_resp.status_code, 200)
        self.assertEqual(layer.mask["type"], "ellipse")

        clear_resp = self.client.patch(
            f"/api/composition/layers/{layer.id}", json={"mask": None}
        )
        self.assertEqual(clear_resp.status_code, 200)
        self.assertIsNone(layer.mask)

    def test_split_export_uses_layer_bounds(self):
        server._project.composition.add_layer(LAYER_A, "A4 Layer", "svg", {})

        response = self.client.get("/api/export?split=1")

        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as zf:
            layer_svg = zf.read("00_A4_Layer.svg").decode()
        self.assertIn('width="210mm"', layer_svg)
        self.assertNotIn('width="297mm"', layer_svg)

    def test_export_emits_per_layer_progress_events(self):
        server._project.composition.add_layer(LAYER_A, "A", "svg", {})
        server._project.composition.add_layer(LAYER_B, "B", "svg", {})

        q = server._subscribe_events()
        try:
            self.client.get("/api/export")
        finally:
            server._unsubscribe_events(q)

        progress = []
        while True:
            try:
                evt = q.get_nowait()
            except Exception:
                break
            if evt.get("t") == "progress" and evt.get("phase") == "export":
                progress.append(evt)

        self.assertTrue(progress, "expected export progress events")
        self.assertEqual(progress[-1]["done"], 2)
        self.assertEqual(progress[-1]["total"], 2)

    def test_export_cancel_endpoint_sets_stop_flag(self):
        server._export_stop_event.clear()
        try:
            response = self.client.post("/api/export/cancel")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(server._export_stop_event.is_set())
        finally:
            server._export_stop_event.clear()

    def test_cancelled_export_returns_409_without_a_partial_file(self):
        server._project.composition.add_layer(LAYER_A, "A", "svg", {})

        def fake_compose(comp, on_progress=None):
            # Simulate a cancel arriving mid-compose.
            server._export_stop_event.set()
            on_progress(0, 1)  # raises __stopped__
            return "<svg/>"

        with mock.patch.object(server, "compose_visible_svg", fake_compose):
            response = self.client.get("/api/export")

        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.get_json().get("canceled"))
        server._export_stop_event.clear()
