import unittest

import web.server as server


SIMPLE_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="10mm" viewBox="0 0 20 10">
  <path d="M0 0 L10 0 L10 10"/>
</svg>"""


class PlotEstimateTest(unittest.TestCase):
    def setUp(self):
        self.old_svg = server._current_svg
        self.old_placement = server._placement
        self.old_cfg = server.cfg.copy()
        server._current_svg = SIMPLE_SVG
        server._placement = {"x": 0.0, "y": 0.0}
        server.cfg.update(
            {
                "speed_pendown": 600,
                "speed_penup": 1200,
                "pen_pos_up": 0,
                "pen_pos_down": 2,
                "pen_rate_raise": 600,
                "pen_rate_lower": 600,
                "pen_delay_up": 100,
                "pen_delay_down": 200,
                "copies": 2,
                "page_delay": 5,
                "reordering": 0,
                "curve_step_mm": 0.5,
            }
        )
        self.client = server.app.test_client()

    def tearDown(self):
        server._current_svg = self.old_svg
        server._placement = self.old_placement
        server.cfg.clear()
        server.cfg.update(self.old_cfg)

    def test_estimate_current_plot_breaks_down_distance_and_time(self):
        response = self.client.get("/api/plot/estimate")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["paths"], 1)
        self.assertEqual(payload["segments"], 2)
        self.assertEqual(payload["copies"], 2)
        self.assertEqual(payload["total_segments"], 4)
        self.assertAlmostEqual(payload["draw_distance_mm"], 40.0, places=2)
        self.assertAlmostEqual(payload["travel_distance_mm"], 28.28, places=2)
        self.assertAlmostEqual(payload["breakdown"]["draw_seconds"], 4.0, places=2)
        self.assertAlmostEqual(payload["breakdown"]["travel_seconds"], 1.41, places=2)
        self.assertAlmostEqual(payload["breakdown"]["copy_delay_seconds"], 5.0, places=2)
        self.assertAlmostEqual(payload["breakdown"]["pen_seconds"], 1.4, places=2)
        self.assertAlmostEqual(payload["estimated_seconds"], 11.81, places=2)

    def test_estimate_requires_a_loaded_svg(self):
        server._current_svg = None

        response = self.client.get("/api/plot/estimate")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "No SVG loaded")


if __name__ == "__main__":
    unittest.main()
