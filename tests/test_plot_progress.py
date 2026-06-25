import unittest

import web.server as server


class PlotProgressTest(unittest.TestCase):
    def test_progress_payload_reports_elapsed_remaining_and_shapes(self):
        payload = server._plot_progress_payload(
            done_segments=50,
            total_segments=100,
            done_shapes=4,
            total_shapes=10,
            started_at=1000.0,
            now=1030.0,
        )

        self.assertEqual(payload["done"], 50)
        self.assertEqual(payload["total"], 100)
        self.assertEqual(payload["segments_remaining"], 50)
        self.assertEqual(payload["shapes_done"], 4)
        self.assertEqual(payload["shapes_total"], 10)
        self.assertEqual(payload["shapes_remaining"], 6)
        self.assertAlmostEqual(payload["elapsed_seconds"], 30.0)
        self.assertAlmostEqual(payload["remaining_seconds"], 30.0)
        self.assertAlmostEqual(payload["progress_fraction"], 0.5)

    def test_progress_payload_handles_zero_total(self):
        payload = server._plot_progress_payload(
            done_segments=0,
            total_segments=0,
            done_shapes=0,
            total_shapes=0,
            started_at=1000.0,
            now=1012.5,
        )

        self.assertEqual(payload["remaining_seconds"], None)
        self.assertEqual(payload["progress_fraction"], 0.0)


if __name__ == "__main__":
    unittest.main()
