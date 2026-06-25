import tempfile
import unittest
from pathlib import Path

import web.server as server


class PlotJobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = server.PLOT_JOB_PATH
        self.old_thread = server._plot_thread
        server.PLOT_JOB_PATH = Path(self.tmp.name) / "plot-job.json"
        server._plot_thread = None

    def tearDown(self):
        server.PLOT_JOB_PATH = self.old_path
        server._plot_thread = self.old_thread
        self.tmp.cleanup()

    def test_create_plot_job_persists_svg_settings_and_placement(self):
        job = server._create_plot_job(
            b"<svg></svg>",
            {"copies": 2, "speed_pendown": 1234},
            {"x": 10.5, "y": 2.25},
        )

        loaded = server._load_plot_job()

        self.assertEqual(loaded["id"], job["id"])
        self.assertEqual(server._plot_job_svg_bytes(loaded), b"<svg></svg>")
        self.assertEqual(loaded["settings"]["speed_pendown"], 1234)
        self.assertEqual(loaded["placement"], {"x": 10.5, "y": 2.25})
        self.assertEqual(loaded["next_copy"], 0)
        self.assertEqual(loaded["next_path"], 0)
        self.assertEqual(loaded["status"], "queued")

    def test_checkpoint_records_next_unfinished_path(self):
        job = server._create_plot_job(b"<svg></svg>", {"copies": 1}, {"x": 0, "y": 0})

        server._checkpoint_plot_job(
            job,
            status="running",
            total_paths=4,
            total_segments=40,
            total_shapes=4,
            next_copy=0,
            next_path=2,
            completed_shapes=2,
            completed_segments=20,
        )

        loaded = server._load_plot_job()
        self.assertEqual(loaded["next_copy"], 0)
        self.assertEqual(loaded["next_path"], 2)
        self.assertEqual(loaded["completed_shapes"], 2)
        self.assertEqual(loaded["completed_segments"], 20)
        self.assertTrue(server._plot_job_public(loaded)["resumable"])

    def test_running_job_is_reported_as_crashed_after_restart(self):
        job = server._create_plot_job(b"<svg></svg>", {"copies": 1}, {"x": 0, "y": 0})
        server._checkpoint_plot_job(
            job,
            status="running",
            total_paths=3,
            total_segments=30,
            total_shapes=3,
            next_copy=0,
            next_path=1,
            completed_shapes=1,
            completed_segments=10,
        )

        client = server.app.test_client()
        response = client.get("/api/plot/job")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["exists"])
        self.assertEqual(payload["status"], "crashed")
        self.assertTrue(payload["resumable"])
        self.assertEqual(payload["shapes_remaining"], 2)


if __name__ == "__main__":
    unittest.main()
