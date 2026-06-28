import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from engine import project as project_mod
import web.server as server


class RegionsPersistenceTest(unittest.TestCase):
    def setUp(self):
        self._orig_dir = project_mod.PROJECTS_DIR
        self._tmp = tempfile.TemporaryDirectory()
        project_mod.PROJECTS_DIR = Path(self._tmp.name)

    def tearDown(self):
        project_mod.PROJECTS_DIR = self._orig_dir
        self._tmp.cleanup()

    def test_region_roundtrips_with_mask_file(self):
        project = project_mod.create_project("Regions")
        mask = Image.new("L", (4, 3), 0)
        mask.putpixel((1, 1), 255)

        region = project.add_region(
            name="Face",
            mask=mask,
            positive_points=[{"x": 1, "y": 1}],
            negative_points=[{"x": 3, "y": 2}],
            bbox_px={"x": 1, "y": 1, "width": 1, "height": 1},
        )

        loaded = project_mod.Project.load(project.id)

        self.assertEqual(len(loaded.regions), 1)
        self.assertEqual(loaded.regions[0].id, region.id)
        self.assertEqual(loaded.regions[0].name, "Face")
        self.assertTrue((loaded.dir / loaded.regions[0].mask_path).exists())
        self.assertEqual(loaded.regions[0].positive_points, [{"x": 1, "y": 1}])
        self.assertEqual(loaded.regions[0].negative_points, [{"x": 3, "y": 2}])

    def test_apply_region_mask_multiplies_source_alpha(self):
        project = project_mod.create_project("Mask")
        src = Image.new("RGBA", (3, 2), (10, 20, 30, 128))
        buf = io.BytesIO()
        src.save(buf, format="PNG")
        project.set_image(buf.getvalue(), "source.png")
        mask = Image.new("L", (3, 2), 0)
        mask.putpixel((1, 0), 255)
        mask.putpixel((2, 1), 128)
        region = project.add_region(name="Cut", mask=mask)

        out = project.open_region_image(region.id)

        self.assertEqual(out.mode, "RGBA")
        self.assertEqual(out.getpixel((0, 0))[3], 0)
        self.assertEqual(out.getpixel((1, 0))[3], 128)
        self.assertEqual(out.getpixel((2, 1))[3], 64)

    def test_replacing_source_image_clears_regions(self):
        project = project_mod.create_project("Replace")
        first = io.BytesIO()
        Image.new("RGB", (2, 2), "white").save(first, format="PNG")
        project.set_image(first.getvalue(), "first.png")
        project.add_region(name="Old", mask=Image.new("L", (2, 2), 255))

        second = io.BytesIO()
        Image.new("RGB", (3, 3), "black").save(second, format="PNG")
        project.set_image(second.getvalue(), "second.png")

        self.assertEqual(project.regions, [])
        self.assertIsNone(project.selected_region_id)
        self.assertEqual(list(project.regions_dir.glob("*.png")), [])


class FakeSegmentationAdapter:
    def status(self):
        return {"available": True, "backend": "fake", "model": "test"}

    def predict(self, image, positive_points, negative_points):
        mask = Image.new("L", image.size, 0)
        for point in positive_points:
            mask.putpixel((int(point["x"]), int(point["y"])), 255)
        return mask


class RegionsApiTest(unittest.TestCase):
    def setUp(self):
        self._orig_dir = project_mod.PROJECTS_DIR
        self._orig_project = server._project
        self._orig_adapter = server._segmentation_adapter
        self._tmp = tempfile.TemporaryDirectory()
        project_mod.PROJECTS_DIR = Path(self._tmp.name)
        server._project = project_mod.create_project("API")
        server._segmentation_adapter = FakeSegmentationAdapter()
        self.client = server.app.test_client()

    def tearDown(self):
        server._segmentation_adapter = self._orig_adapter
        server._project = self._orig_project
        project_mod.PROJECTS_DIR = self._orig_dir
        self._tmp.cleanup()

    def _upload_image(self):
        buf = io.BytesIO()
        Image.new("RGB", (5, 4), "white").save(buf, format="PNG")
        response = self.client.post(
            "/api/image",
            data={"file": (io.BytesIO(buf.getvalue()), "sample.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)

    def test_segmentation_predict_and_save_region(self):
        self._upload_image()

        predict = self.client.post(
            "/api/segmentation/predict",
            json={"positive_points": [{"x": 2, "y": 1}], "negative_points": []},
        )
        self.assertEqual(predict.status_code, 200)
        payload = predict.get_json()
        self.assertEqual(payload["bbox_px"], {"x": 2, "y": 1, "width": 1, "height": 1})

        create = self.client.post(
            "/api/regions",
            json={
                "name": "Eye",
                "mask_png": payload["mask_png"],
                "positive_points": [{"x": 2, "y": 1}],
                "negative_points": [],
                "bbox_px": payload["bbox_px"],
            },
        )

        self.assertEqual(create.status_code, 200)
        regions = create.get_json()["regions"]
        self.assertEqual(regions[0]["name"], "Eye")
        mask_response = self.client.get(f"/api/regions/{regions[0]['id']}/mask")
        self.assertEqual(mask_response.status_code, 200)
        self.assertEqual(mask_response.mimetype, "image/png")
        mask_response.close()

    def test_process_rejects_missing_region(self):
        self._upload_image()

        response = self.client.post(
            "/api/process",
            json={"pfm_id": "voronoi_stippling", "params": {}, "region_id": "missing"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("Unknown region", response.get_json()["error"])


class SmartRegionLayerApiTest(unittest.TestCase):
    def setUp(self):
        self._orig_dir = project_mod.PROJECTS_DIR
        self._orig_project = server._project
        self._tmp = tempfile.TemporaryDirectory()
        project_mod.PROJECTS_DIR = Path(self._tmp.name)
        server._project = project_mod.create_project("Smart Layers")
        self.client = server.app.test_client()

        src = io.BytesIO()
        Image.new("RGBA", (4, 3), (10, 20, 30, 255)).save(src, format="PNG")
        server._project.set_image(src.getvalue(), "source.png")
        mask = Image.new("L", (4, 3), 0)
        mask.putpixel((1, 1), 255)
        mask.putpixel((2, 1), 255)
        self.region = server._project.add_region(
            name="Face",
            mask=mask,
            bbox_px={"x": 1, "y": 1, "width": 2, "height": 1},
        )

    def tearDown(self):
        server._project = self._orig_project
        project_mod.PROJECTS_DIR = self._orig_dir
        self._tmp.cleanup()

    def test_masked_raster_endpoint_returns_region_alpha(self):
        layer = server._project.composition.add_layer(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" viewBox="0 0 10 10"></svg>',
            "Face",
            "pathfinding",
            {},
        )
        layer.region_id = self.region.id
        layer.display_mode = "raster"
        server._project.save_composition_layers()

        response = self.client.get(f"/api/composition/layers/{layer.id}/raster")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        image = Image.open(io.BytesIO(response.data)).convert("RGBA")
        # The endpoint serves the prepared raster (matches what pathfinding
        # analysed), so exact dimensions/positions vary — but the region alpha
        # must survive: both fully transparent and fully opaque pixels present.
        self.assertEqual(image.getchannel("A").getextrema(), (0, 255))

    def test_layer_style_generation_updates_only_target_layer(self):
        target = server._project.composition.add_layer(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" viewBox="0 0 10 10"><path d="M0 0 L1 1"/></svg>',
            "Face",
            "pathfinding",
            {},
        )
        target.region_id = self.region.id
        other = server._project.composition.add_layer(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" viewBox="0 0 10 10"><path d="M2 2 L3 3"/></svg>',
            "Background",
            "pathfinding",
            {},
        )
        old_other_svg = other.svg
        fake_pfm = mock.Mock()
        fake_pfm.id = "fake_pfm"
        fake_pfm.name = "Fake PFM"
        fake_pfm.params = []
        fake_pfm.run.return_value = object()
        server.REGISTRY[fake_pfm.id] = fake_pfm
        try:
            with mock.patch.object(server.svg_io, "to_svg", return_value='<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" viewBox="0 0 10 10"><path d="M4 4 L5 5"/></svg>'):
                response = self.client.post(
                    f"/api/composition/layers/{target.id}/pathfinding/generate",
                    json={"pfm_id": fake_pfm.id, "params": {"seed": 4}},
                )
        finally:
            server.REGISTRY.pop(fake_pfm.id, None)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        layers = {layer["id"]: layer for layer in payload["composition"]["layers"]}
        self.assertIn("M4 4 L5 5", target.svg)
        self.assertEqual(other.svg, old_other_svg)
        self.assertEqual(layers[target.id]["pathfinding_style"]["status"], "clean")
        self.assertEqual(layers[target.id]["pathfinding_style"]["pfm_id"], fake_pfm.id)
        self.assertEqual(layers[target.id]["source"]["region_id"], self.region.id)
        self.assertEqual(layers[target.id]["occlusion_mask"], {"type": "rect", "x": 2.5, "y": 3.3333, "width": 5.0, "height": 3.3333})

    def test_layer_style_generation_without_region_uses_whole_image(self):
        # Path finding is an effect on the layer; a region is optional. Without
        # one it runs on the whole image and occludes the full layer footprint.
        target = server._project.composition.add_layer(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" viewBox="0 0 10 10"></svg>',
            "Whole",
            "pathfinding",
            {},
        )
        fake_pfm = mock.Mock()
        fake_pfm.id = "fake_pfm"
        fake_pfm.name = "Fake PFM"
        fake_pfm.params = []
        fake_pfm.run.return_value = object()
        server.REGISTRY[fake_pfm.id] = fake_pfm
        try:
            with mock.patch.object(server.svg_io, "to_svg", return_value='<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" viewBox="0 0 10 10"><path d="M4 4 L5 5"/></svg>'):
                response = self.client.post(
                    f"/api/composition/layers/{target.id}/pathfinding/generate",
                    json={"pfm_id": fake_pfm.id, "params": {}},
                )
        finally:
            server.REGISTRY.pop(fake_pfm.id, None)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        layer = {l["id"]: l for l in payload["composition"]["layers"]}[target.id]
        self.assertIn("M4 4 L5 5", target.svg)
        self.assertEqual(layer["pathfinding_style"]["status"], "clean")
        self.assertIsNone(layer["region_id"])
        self.assertIsNone(layer["source"]["region_id"])
        self.assertEqual(
            layer["occlusion_mask"],
            {"type": "rect", "x": 0.0, "y": 0.0, "width": 10.0, "height": 10.0},
        )

    def test_add_layer_endpoint_creates_empty_pathfinding_layer(self):
        before = len(server._project.composition.layers)
        response = self.client.post("/api/composition/add-layer", json={})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        layers = payload["composition"]["layers"]
        self.assertEqual(len(layers), before + 1)
        new = layers[-1]
        self.assertEqual(new["kind"], "pathfinding")
        self.assertEqual(payload["composition"]["selected_layer_id"], new["id"])
        self.assertNotIn("<path", new["svg"])


class WorkflowLayerSeparationTest(unittest.TestCase):
    """Generate and path finding are separate workflows: neither overwrites the
    other's layer. _set_workflow_layer reuses the selected layer only when it is
    on the same side of the generate/non-generate divide."""

    SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" '
           'viewBox="0 0 10 10"></svg>')

    def setUp(self):
        self._orig_dir = project_mod.PROJECTS_DIR
        self._orig_project = server._project
        self._tmp = tempfile.TemporaryDirectory()
        project_mod.PROJECTS_DIR = Path(self._tmp.name)
        server._project = project_mod.create_project("Workflows")

    def tearDown(self):
        server._project = self._orig_project
        project_mod.PROJECTS_DIR = self._orig_dir
        self._tmp.cleanup()

    def test_generate_does_not_clobber_selected_pathfinding_layer(self):
        comp = server._project.composition
        pf = comp.add_layer(self.SVG, "Face", "pathfinding", {})  # becomes selected
        server._set_workflow_layer(self.SVG, "Spokes", "generate",
                                   {"generator_id": "spokes_and_circles"})
        self.assertEqual(len(comp.layers), 2)
        self.assertTrue(any(l.id == pf.id and l.kind == "pathfinding" for l in comp.layers))
        self.assertTrue(any(l.kind == "generate" for l in comp.layers))

    def test_regenerate_replaces_selected_generate_layer_in_place(self):
        comp = server._project.composition
        gen = comp.add_layer(self.SVG, "Spokes", "generate", {})  # becomes selected
        server._set_workflow_layer(self.SVG, "Spokes", "generate", {})
        self.assertEqual(len(comp.layers), 1)
        self.assertEqual(comp.layers[0].id, gen.id)

    def test_pathfinding_does_not_clobber_selected_generate_layer(self):
        comp = server._project.composition
        gen = comp.add_layer(self.SVG, "Spokes", "generate", {})  # becomes selected
        server._set_workflow_layer(self.SVG, "Face", "pathfinding", {})
        self.assertEqual(len(comp.layers), 2)
        self.assertTrue(any(l.id == gen.id and l.kind == "generate" for l in comp.layers))


class LocalSam2SetupTest(unittest.TestCase):
    def test_status_auto_installs_missing_package_and_downloads_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "sam2.1_hiera_tiny.pt"
            adapter = server.LocalSam2Adapter(checkpoint=str(checkpoint))
            installed = {"ready": False}

            def has_module(name):
                return name == "torch" or installed["ready"]

            with mock.patch.object(adapter, "_has_module", side_effect=lambda name: name == "torch"), \
                mock.patch.object(adapter, "_install_sam2") as install, \
                mock.patch.object(adapter, "_download_checkpoint") as download:
                adapter._has_module.side_effect = has_module
                install.side_effect = lambda: installed.__setitem__("ready", True)
                download.side_effect = lambda: checkpoint.write_bytes(b"model")

                status = adapter.status()

            self.assertTrue(status["available"])
            install.assert_called_once()
            download.assert_called_once()

    def test_status_reports_setup_error_when_auto_install_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = server.LocalSam2Adapter(checkpoint=str(Path(tmp) / "missing.pt"))

            with mock.patch.object(adapter, "_has_module", return_value=False), \
                mock.patch.object(adapter, "_install_sam2", side_effect=RuntimeError("install failed")):
                status = adapter.status()

            self.assertFalse(status["available"])
            self.assertEqual(status["setup_state"], "error")
            self.assertIn("install failed", status["error"])

    def test_install_sam2_falls_back_to_uv_when_pip_module_is_missing(self):
        adapter = server.LocalSam2Adapter()
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            stderr = "No module named pip" if len(calls) == 1 else ""
            return mock.Mock(returncode=1 if len(calls) == 1 else 0, stderr=stderr, stdout="")

        with mock.patch("subprocess.run", side_effect=fake_run), \
            mock.patch("importlib.invalidate_caches"):
            adapter._install_sam2()

        self.assertEqual(calls[0][1:4], ["-m", "pip", "install"])
        self.assertEqual(calls[1][0:3], ["uv", "pip", "install"])

    def test_device_prefers_cpu_when_cuda_and_mps_are_unavailable(self):
        torch = mock.Mock()
        torch.cuda.is_available.return_value = False
        torch.backends.mps.is_available.return_value = False

        self.assertEqual(server.LocalSam2Adapter._device_for(torch), "cpu")


if __name__ == "__main__":
    unittest.main()
