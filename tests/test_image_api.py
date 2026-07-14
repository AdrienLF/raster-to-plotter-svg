import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import engine.project as project_mod
import web.server as server


class ImageApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_projects_dir = project_mod.PROJECTS_DIR
        project_mod.PROJECTS_DIR = Path(self.tmp.name)
        self.old_project = server._project
        server._project = project_mod.create_project("Image API test")
        self.client = server.app.test_client()

    def tearDown(self):
        server._project = self.old_project
        project_mod.PROJECTS_DIR = self.old_projects_dir
        self.tmp.cleanup()

    def _png_bytes(self) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (3, 2), "red").save(buf, format="PNG")
        return buf.getvalue()

    def _upload(self):
        return self.client.post(
            "/api/image",
            data={"file": (io.BytesIO(self._png_bytes()), "sample.png")},
            content_type="multipart/form-data",
        )

    def test_upload_returns_image_url_not_embedded_data_url(self):
        response = self._upload()

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["width"], 3)
        self.assertEqual(payload["height"], 2)
        self.assertIn("image_url", payload)
        self.assertNotIn("data_url", payload)

        image_response = self.client.get(payload["image_url"])
        self.assertEqual(image_response.status_code, 200)
        self.assertEqual(image_response.mimetype, "image/png")
        image_response.close()

    def test_upload_creates_a_fitted_raster_layer(self):
        payload = self._upload().get_json()

        layers = payload["composition"]["layers"]
        layer = next(l for l in layers if l["id"] == payload["layer_id"])
        self.assertEqual(layer["kind"], "raster")
        self.assertEqual(layer["name"], "sample")
        self.assertEqual(layer["display_mode"], "raster")
        # Fitted (never cropped) into the drawing area, centred, aspect kept.
        self.assertAlmostEqual(layer["width"] / layer["height"], 3 / 2, places=4)
        ix, iy, iw, ih = server._project.area.inner_rect_mm()
        self.assertAlmostEqual(layer["x"], ix + (iw - layer["width"]) / 2, places=3)
        self.assertAlmostEqual(layer["y"], iy + (ih - layer["height"]) / 2, places=3)
        self.assertLessEqual(layer["width"], iw + 1e-6)
        self.assertLessEqual(layer["height"], ih + 1e-6)

        # The layer owns its raster file, served uncropped.
        raster = self.client.get(f"/api/composition/layers/{layer['id']}/raster")
        self.assertEqual(raster.status_code, 200)
        with Image.open(io.BytesIO(raster.data)) as served:
            self.assertEqual(served.size, (3, 2))
        raster.close()

    def test_raster_layer_accepts_rotation_patch(self):
        payload = self._upload().get_json()
        layer_id = payload["layer_id"]

        response = self.client.patch(
            f"/api/composition/layers/{layer_id}",
            json={"rotation": 405.0},
        )
        self.assertEqual(response.status_code, 200)
        layer = next(l for l in response.get_json()["composition"]["layers"]
                     if l["id"] == layer_id)
        self.assertAlmostEqual(layer["rotation"], 45.0)


if __name__ == "__main__":
    unittest.main()
