"""Raster layers: import -> transformable layer, layer-local generation,
page clipping for out-of-bounds content."""

import io
import re
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import engine.project as project_mod
from engine.composition import compose_visible_svg, parse_svg_size_mm
import web.server as server


class RasterLayerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_projects_dir = project_mod.PROJECTS_DIR
        project_mod.PROJECTS_DIR = Path(self.tmp.name)
        self.old_project = server._project
        server._project = project_mod.create_project("Raster layer test")
        self.client = server.app.test_client()

    def tearDown(self):
        server._project = self.old_project
        project_mod.PROJECTS_DIR = self.old_projects_dir
        self.tmp.cleanup()

    def _upload(self, size=(120, 80)):
        buf = io.BytesIO()
        Image.new("RGB", size, "#555").save(buf, format="PNG")
        buf.seek(0)
        response = self.client.post(
            "/api/image",
            data={"file": (buf, "photo.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()["layer_id"]

    def _layer(self, layer_id):
        return next(l for l in server._project.composition.layers
                    if l.id == layer_id)

    def test_generate_keeps_raster_identity_and_local_coordinates(self):
        layer_id = self._upload()
        layer = self._layer(layer_id)
        width, height = layer.width, layer.height
        x, y = layer.x, layer.y

        response = self.client.post(
            f"/api/composition/layers/{layer_id}/pathfinding/generate",
            json={"pfm_id": "dither_halftone", "params": {"cell_size": 8}},
        )
        self.assertEqual(response.status_code, 200)

        layer = self._layer(layer_id)
        self.assertEqual(layer.kind, "raster")
        self.assertTrue(layer.image_path)
        # Transform and size untouched; strokes live in layer-local mm.
        self.assertEqual((layer.x, layer.y), (x, y))
        self.assertEqual((layer.width, layer.height), (width, height))
        svg_w, svg_h = parse_svg_size_mm(layer.svg)
        self.assertAlmostEqual(svg_w, width, places=1)
        self.assertAlmostEqual(svg_h, height, places=1)
        self.assertEqual(layer.display_mode, "both")

    def test_generation_never_crops_the_source(self):
        # A wide image on a portrait page: the crop-y default scaling_mode
        # must not apply to raster layers (the synthetic area matches the
        # image aspect exactly).
        layer_id = self._upload(size=(300, 100))
        layer = self._layer(layer_id)
        self.assertAlmostEqual(layer.width / layer.height, 3.0, places=3)

        response = self.client.post(
            f"/api/composition/layers/{layer_id}/pathfinding/generate",
            json={"pfm_id": "dither_halftone", "params": {"cell_size": 8}},
        )
        self.assertEqual(response.status_code, 200)
        svg_w, svg_h = parse_svg_size_mm(self._layer(layer_id).svg)
        self.assertAlmostEqual(svg_w / svg_h, 3.0, places=2)

    def test_out_of_bounds_layer_is_page_clipped_at_compose(self):
        layer_id = self._upload()
        self.client.post(
            f"/api/composition/layers/{layer_id}/pathfinding/generate",
            json={"pfm_id": "dither_halftone", "params": {"cell_size": 8}},
        )
        comp = server._project.composition

        svg = compose_visible_svg(comp)
        self.assertNotIn("page-clip", svg)  # fully on page: no clip emitted

        self.client.patch(f"/api/composition/layers/{layer_id}",
                          json={"x": -80.0})
        svg = compose_visible_svg(comp)
        self.assertIn('clipPath id="page-clip"', svg)
        self.assertIn('clip-path="url(#page-clip)"', svg)
        # The clip wraps the transformed group from the outside, so the page
        # rect stays in page coordinates.
        self.assertRegex(
            svg, r'<g clip-path="url\(#page-clip\)"><g data-layer-id=')

    def test_rotation_lands_in_compose_transform(self):
        layer_id = self._upload()
        self.client.post(
            f"/api/composition/layers/{layer_id}/pathfinding/generate",
            json={"pfm_id": "dither_halftone", "params": {"cell_size": 8}},
        )
        self.client.patch(f"/api/composition/layers/{layer_id}",
                          json={"rotation": 30.0})
        svg = compose_visible_svg(server._project.composition)
        match = re.search(r'data-layer-id="' + layer_id + r'"[^>]*transform="([^"]+)"',
                          svg)
        self.assertIsNotNone(match)
        self.assertIn("rotate(30", match.group(1))

    def test_scaled_layer_generates_at_matching_pen_density(self):
        layer_id = self._upload()
        self.client.patch(f"/api/composition/layers/{layer_id}",
                          json={"scale": 0.5})
        response = self.client.post(
            f"/api/composition/layers/{layer_id}/pathfinding/generate",
            json={"pfm_id": "dither_halftone", "params": {"cell_size": 8}},
        )
        self.assertEqual(response.status_code, 200)
        layer = self._layer(layer_id)
        self.assertEqual(layer.scale, 0.5)
        # Layer-local doc size is unchanged by scale; density compensation
        # happens in the synthetic area's pen width.
        svg_w, _ = parse_svg_size_mm(layer.svg)
        self.assertAlmostEqual(svg_w, layer.width, places=1)


if __name__ == "__main__":
    unittest.main()
