import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import web.server as server


class TempProject:
    def __init__(self, root: Path):
        self.dir = root
        self.image_name = ""

    @property
    def image_path(self):
        return self.dir / self.image_name if self.image_name else None

    def set_image(self, data: bytes, filename: str) -> None:
        suffix = Path(filename).suffix.lower() or ".png"
        self.image_name = f"source{suffix}"
        self.image_path.write_bytes(data)


class ImageApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_project = server._project
        server._project = TempProject(Path(self.tmp.name))
        self.client = server.app.test_client()

    def tearDown(self):
        server._project = self.old_project
        self.tmp.cleanup()

    def _png_bytes(self) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (3, 2), "red").save(buf, format="PNG")
        return buf.getvalue()

    def test_upload_returns_image_url_not_embedded_data_url(self):
        response = self.client.post(
            "/api/image",
            data={"file": (io.BytesIO(self._png_bytes()), "sample.png")},
            content_type="multipart/form-data",
        )

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


if __name__ == "__main__":
    unittest.main()
