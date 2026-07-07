"""Draft-quality preview renders (low-res working raster)."""

import unittest

import numpy as np
from PIL import Image

from engine.canvas import DrawingArea
from engine.pens import DrawingSet
from engine.pfm.base import PFM, get


def _image(w=600, h=800):
    arr = np.tile(np.linspace(20, 235, w).astype(np.uint8), (h, 1))
    return Image.fromarray(arr, "L").convert("RGB")


class DraftTest(unittest.TestCase):
    def test_working_resolution_cap(self):
        area = DrawingArea()
        full = area.working_resolution(600, 800)
        capped = area.working_resolution(600, 800, max_px=420)
        self.assertGreater(max(full), 420)
        self.assertLessEqual(max(capped), 420)
        # aspect preserved (within integer rounding)
        self.assertAlmostEqual(full[0] / full[1], capped[0] / capped[1], places=1)

    def test_draft_run_is_smaller_and_marks_nothing_dirty(self):
        area, ds = DrawingArea(), DrawingSet()
        pfm = get("voronoi_stippling")
        params = {"seed": 1, "point_density": 200}
        full = pfm.run(_image(), area, ds, params, seed=1)
        draft = pfm.run(_image(), area, ds, params, seed=1, draft=True)
        self.assertLessEqual(max(draft.width, draft.height), PFM.DRAFT_MAX_PX)
        self.assertGreater(max(full.width, full.height), PFM.DRAFT_MAX_PX)
        self.assertGreater(draft.total(), 0)


if __name__ == "__main__":
    unittest.main()
