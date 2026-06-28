import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from engine import project as project_mod
from engine.composition import Composition
from engine.versioning import Version
import web.server as server


GENERATOR_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="80mm" viewBox="0 0 100 80">
  <path d="M10 10 L90 70" fill="none" stroke="#123456"/>
</svg>"""


class VersionApiTest(unittest.TestCase):
    def setUp(self):
        self._orig_projects_dir = project_mod.PROJECTS_DIR
        self._orig_project = server._project
        self._orig_drawing = server._drawing
        self._orig_current_svg = server._current_svg
        self._orig_composition_dirty = server._composition_dirty
        self._orig_placement = server._placement
        self._orig_stop_set = server._stop_event.is_set()

        self._tmp = tempfile.TemporaryDirectory()
        project_mod.PROJECTS_DIR = Path(self._tmp.name)
        server._project = project_mod.create_project("Versions")
        server._drawing = None
        server._current_svg = None
        server._composition_dirty = True
        server._placement = {"x": 0.0, "y": 0.0}
        self.client = server.app.test_client()

    def tearDown(self):
        project_mod.PROJECTS_DIR = self._orig_projects_dir
        server._project = self._orig_project
        server._drawing = self._orig_drawing
        server._current_svg = self._orig_current_svg
        server._composition_dirty = self._orig_composition_dirty
        server._placement = self._orig_placement
        if self._orig_stop_set:
            server._stop_event.set()
        else:
            server._stop_event.clear()
        self._tmp.cleanup()

    def add_generator_layer(self):
        layer = server._project.composition.add_layer(
            GENERATOR_SVG,
            name="Generator layer",
            kind="generate",
            source={"generator_id": "test", "params": {"seed": 7}},
        )
        server._project.save_composition_layers()
        server._sync_current_svg_from_composition()
        return layer

    def test_generator_composition_version_saves_thumbnail_and_external_snapshot(self):
        layer = self.add_generator_layer()

        response = self.client.post("/api/versions", json={"name": "Generator snapshot"})

        self.assertEqual(response.status_code, 200, response.get_json())
        version = response.get_json()["version"]
        self.assertEqual(version["name"], "Generator snapshot")
        self.assertTrue(version["composition_snapshot"])

        thumbnail_path = server._project.dir / version["thumbnail"]
        snapshot_path = server._project.dir / version["composition_snapshot"]
        self.assertTrue(thumbnail_path.is_file())
        self.assertTrue(snapshot_path.is_file())
        with Image.open(thumbnail_path) as thumbnail:
            self.assertEqual(thumbnail.format, "PNG")
            self.assertGreater(thumbnail.width, 1)
            self.assertGreater(thumbnail.height, 1)
            self.assertLessEqual(thumbnail.width, 260)
            self.assertLessEqual(thumbnail.height, 260)
            self.assertTrue(
                any(low < 255 for low, _high in thumbnail.convert("RGB").getextrema()),
                "normalized thumbnail should contain rendered geometry",
            )

        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["selected_layer_id"], layer.id)
        self.assertEqual(snapshot["layers"][0]["svg"], GENERATOR_SVG)

        project_manifest = json.loads((server._project.dir / "project.json").read_text(encoding="utf-8"))
        saved_version = project_manifest["versions"][0]
        self.assertEqual(saved_version["composition_snapshot"], version["composition_snapshot"])
        self.assertNotIn("svg", saved_version)
        self.assertNotIn(GENERATOR_SVG, (server._project.dir / "project.json").read_text(encoding="utf-8"))

    def test_empty_project_version_save_still_returns_400(self):
        response = self.client.post("/api/versions", json={"name": "Nothing"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Nothing to save — process a drawing first")

    def test_generator_version_thumbnail_ignores_plot_cancellation(self):
        self.add_generator_layer()
        server._stop_event.set()

        response = self.client.post("/api/versions", json={"name": "After stop"})

        self.assertEqual(response.status_code, 200, response.get_json())
        thumbnail_path = server._project.dir / response.get_json()["version"]["thumbnail"]
        with Image.open(thumbnail_path) as thumbnail:
            self.assertTrue(
                any(low < 255 for low, _high in thumbnail.convert("RGB").getextrema())
            )

    def test_missing_composition_snapshot_load_is_atomic_and_controlled(self):
        self.add_generator_layer()
        save_response = self.client.post("/api/versions", json={"name": "Broken snapshot"})
        version = server._project.get_version(save_response.get_json()["version"]["id"])
        (server._project.dir / version.composition_snapshot).unlink()

        server._project.pfm_id = "spiral"
        server._project.params = {"current": 11}
        server._project.area.width = 123
        server._project.drawing_set.distribution_type = "single"
        server._project.composition = Composition()
        server._project.composition.add_layer(
            GENERATOR_SVG.replace("M10 10 L90 70", "M5 5 L20 20"),
            "Current layer",
            "svg",
            {"current": True},
        )
        before = {
            "pfm_id": server._project.pfm_id,
            "params": dict(server._project.params),
            "area": server._project.area.to_dict(),
            "drawing_set": server._project.drawing_set.to_dict(),
            "composition": server._project.composition.to_dict(include_svg=True),
        }
        drawing = object()
        current_svg = b"<svg>current</svg>"
        server._drawing = drawing
        server._current_svg = current_svg
        server._composition_dirty = False

        response = self.client.post(f"/api/versions/{version.id}/load")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json()["error"],
            "Version snapshot is unavailable or invalid",
        )
        self.assertEqual(server._project.pfm_id, before["pfm_id"])
        self.assertEqual(server._project.params, before["params"])
        self.assertEqual(server._project.area.to_dict(), before["area"])
        self.assertEqual(server._project.drawing_set.to_dict(), before["drawing_set"])
        self.assertEqual(
            server._project.composition.to_dict(include_svg=True),
            before["composition"],
        )
        self.assertIs(server._drawing, drawing)
        self.assertEqual(server._current_svg, current_svg)

    def test_load_restores_saved_generator_composition_exactly(self):
        self.add_generator_layer()
        save_response = self.client.post("/api/versions", json={"name": "Restore generator"})
        version = save_response.get_json()["version"]
        snapshot_path = server._project.dir / version["composition_snapshot"]
        saved_composition = json.loads(snapshot_path.read_text(encoding="utf-8"))

        server._project.composition.layers.clear()
        server._project.composition.selected_layer_id = None
        server._project.save_composition_layers()
        server._drawing = object()
        server._current_svg = None
        server._composition_dirty = True

        load_response = self.client.post(f"/api/versions/{version['id']}/load")

        self.assertEqual(load_response.status_code, 200, load_response.get_json())
        restored = load_response.get_json()["composition"]
        self.assertEqual(restored, saved_composition)
        self.assertEqual(server._project.composition.to_dict(include_svg=True), saved_composition)
        self.assertIsNone(server._drawing)
        self.assertIn(b"M10 10 L90 70", server._current_svg)

    def test_legacy_version_load_keeps_settings_only_response(self):
        legacy = Version(
            id="legacy01",
            name="Legacy",
            pfm_id="spiral",
            params={"seed": 3},
            area=server._project.area.to_dict(),
            drawing_set=server._project.drawing_set.to_dict(),
        )
        server._project.versions.append(legacy)
        server._project.save()

        response = self.client.post("/api/versions/legacy01/load")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("composition", response.get_json())
        self.assertEqual(response.get_json()["pfm_id"], "spiral")
        self.assertEqual(response.get_json()["params"], {"seed": 3})

    def test_version_from_dict_accepts_legacy_data_without_snapshot(self):
        legacy = Version.from_dict(
            {
                "id": "legacy02",
                "name": "Legacy",
                "pfm_id": "spiral",
                "params": {},
                "area": server._project.area.to_dict(),
                "drawing_set": server._project.drawing_set.to_dict(),
            }
        )

        self.assertEqual(legacy.composition_snapshot, "")


if __name__ == "__main__":
    unittest.main()
