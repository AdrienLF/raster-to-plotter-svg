import os
import tempfile
import unittest
from pathlib import Path

from engine import svg_io
from engine.pens import DrawingSet, Pen
import web.server as server


# A composed 2-pen page: two Inkscape layer groups (Black, Blue) nested inside a
# composition-layer <g transform>, mirroring compose_visible_svg's output. The
# inkscape attributes use a namespace prefix, exactly as ElementTree re-serializes
# them in the real composed document.
TWO_PEN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
    'viewBox="0 0 100 100">'
    '<g data-layer-id="L1" transform="translate(0 0)">'
    '<g xmlns:ns0="http://www.inkscape.org/namespaces/inkscape" '
    'ns0:groupmode="layer" ns0:label="Black" fill="none" stroke="#000000">'
    '<path d="M0,0 L10,0"/><path d="M0,5 L10,5"/></g>'
    '<g xmlns:ns0="http://www.inkscape.org/namespaces/inkscape" '
    'ns0:groupmode="layer" ns0:label="Blue" fill="none" stroke="#0000ff">'
    '<path d="M0,10 L10,10"/></g>'
    '</g></svg>'
).encode()

ONE_PEN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
    'viewBox="0 0 100 100">'
    '<g data-layer-id="L1" transform="translate(0 0)">'
    '<g xmlns:ns0="http://www.inkscape.org/namespaces/inkscape" '
    'ns0:groupmode="layer" ns0:label="Black" fill="none" stroke="#000000">'
    '<path d="M0,0 L10,0"/></g></g></svg>'
).encode()


class SplitSvgByPenTest(unittest.TestCase):
    def test_splits_into_one_svg_per_pen_in_order(self):
        parts = svg_io.split_svg_by_pen(TWO_PEN_SVG, [("Blue", "#0000ff"), ("Black", "#000000")])
        self.assertEqual([p["name"] for p in parts], ["Blue", "Black"])  # pen-list order
        by_name = {p["name"]: p for p in parts}
        self.assertEqual(by_name["Black"]["shapes"], 2)
        self.assertEqual(by_name["Blue"]["shapes"], 1)
        self.assertEqual(by_name["Blue"]["colour"], "#0000ff")

    def test_split_geometry_partitions_the_whole_drawing(self):
        settings = {"reordering": "none"}
        whole = server.svg_to_polylines(TWO_PEN_SVG, settings, respect_stop=False)
        parts = svg_io.split_svg_by_pen(TWO_PEN_SVG, [("Black", "#000000"), ("Blue", "#0000ff")])
        split_total = sum(
            len(server.svg_to_polylines(p["svg"].encode(), settings, respect_stop=False))
            for p in parts
        )
        self.assertEqual(split_total, len(whole))

    def test_single_pen_returns_one_entry(self):
        parts = svg_io.split_svg_by_pen(ONE_PEN_SVG, [("Black", "#000000")])
        self.assertEqual(len(parts), 1)

    def test_no_labels_returns_empty(self):
        plain = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0,0 L1,1"/></svg>'
        self.assertEqual(svg_io.split_svg_by_pen(plain, []), [])


# Cavalry-style: raw unlabelled markup inside a scale() wrap, px coords, stroke
# colours near (not equal to) the pen palette, plus one clip-path'd path + defs.
CAVALRY_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
    'viewBox="0 0 100 100">'
    '<defs><clipPath id="half"><rect x="0" y="0" width="50" height="1000"/></clipPath></defs>'
    '<g transform="scale(0.5)">'
    '<path d="M0,0 L200,0" stroke="#c81e12"/>'          # near Red, unclipped
    '<path d="M0,40 L200,40" stroke="#000000"/>'        # Black
    '<g clip-path="url(#half)"><path d="M0,80 L200,80" stroke="#c81e12"/></g>'  # near Red, clipped
    '</g></svg>'
).encode()

# Labelled Black group + an unlabelled near-black stroke (masked-layer style).
MIXED_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
    'viewBox="0 0 100 100">'
    '<g xmlns:ns0="http://www.inkscape.org/namespaces/inkscape" '
    'ns0:label="Black" fill="none" stroke="#000000"><path d="M0,0 L10,0"/></g>'
    '<path d="M0,5 L10,5" stroke="#0a0a0a"/>'
    '</svg>'
).encode()

CAVALRY_PENS = [("Black", "#000000"), ("Red", "#c0392b")]


class CavalrySplitTest(unittest.TestCase):
    def test_unlabelled_matches_nearest_pen_by_colour(self):
        parts = svg_io.split_svg_by_pen(CAVALRY_SVG, CAVALRY_PENS)
        self.assertEqual([p["name"] for p in parts], ["Black", "Red"])  # pen order
        by_name = {p["name"]: p for p in parts}
        self.assertEqual(by_name["Black"]["shapes"], 1)
        self.assertEqual(by_name["Red"]["shapes"], 2)  # unclipped + clipped

    def test_split_partitions_whole_drawing(self):
        settings = {"reordering": "none"}
        whole = server.svg_to_polylines(CAVALRY_SVG, settings, respect_stop=False)
        parts = svg_io.split_svg_by_pen(CAVALRY_SVG, CAVALRY_PENS)
        split_total = sum(
            len(server.svg_to_polylines(p["svg"].encode(), settings, respect_stop=False))
            for p in parts
        )
        self.assertEqual(split_total, len(whole))

    def test_clipped_path_stays_clipped_in_its_pen(self):
        settings = {"reordering": "none"}
        parts = svg_io.split_svg_by_pen(CAVALRY_SVG, CAVALRY_PENS)
        red = next(p for p in parts if p["name"] == "Red")
        polys = server.svg_to_polylines(red["svg"].encode(), settings, respect_stop=False)
        # clip rect (width 50) keeps the clipped red run to x<=50mm; the
        # unclipped red run reaches the full 100mm — one poly per run.
        spans = sorted((min(x for x, _ in p), max(x for x, _ in p)) for p in polys)
        self.assertEqual(len(spans), 2)
        self.assertAlmostEqual(spans[0][1], 50, delta=0.6)   # clipped run ends at ~50mm
        self.assertAlmostEqual(spans[1][1], 100, delta=0.6)  # unclipped run full width

    def test_mixed_labelled_and_unlabelled_join_one_bucket(self):
        parts = svg_io.split_svg_by_pen(MIXED_SVG, [("Black", "#000000"), ("Blue", "#0000ff")])
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]["name"], "Black")
        self.assertEqual(parts[0]["shapes"], 2)  # labelled + unlabelled, not dropped

    def test_filled_no_stroke_shape_matches_by_fill(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<rect x="0" y="0" width="10" height="10" fill="#050505"/></svg>'
        ).encode()
        parts = svg_io.split_svg_by_pen(svg, CAVALRY_PENS)
        self.assertEqual([p["name"] for p in parts], ["Black"])  # nearest to fill


class MultiPenJobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = server.PLOT_JOB_PATH
        self.old_cache = server.PLOT_PATHS_CACHE
        self.old_thread = server._plot_thread
        self.old_ds = server._project.drawing_set
        self.old_wait = server._wait_pen_change
        self.old_stop = server._stop_event.is_set()
        server.PLOT_JOB_PATH = Path(self.tmp.name) / "plot-job.json"
        server.PLOT_PATHS_CACHE = Path(self.tmp.name) / "plot-paths.pkl"
        server._plot_thread = None
        server._stop_event.clear()
        server._pen_change_event.clear()
        # Two enabled pens → _pen_order() returns Black then Blue.
        server._project.drawing_set = DrawingSet(pens=[
            Pen(name="Black", colour="#000000"),
            Pen(name="Blue", colour="#0000ff"),
        ])
        os.environ["PLOTTER_FAKE_SERIAL"] = "1"
        server._FAKE_SERIAL_WRITES.clear()
        # Don't actually block on operator confirmation in the test.
        server._wait_pen_change = lambda *a, **k: None

    def tearDown(self):
        server.PLOT_JOB_PATH = self.old_path
        server.PLOT_PATHS_CACHE = self.old_cache
        server._plot_thread = self.old_thread
        server._project.drawing_set = self.old_ds
        server._wait_pen_change = self.old_wait
        os.environ.pop("PLOTTER_FAKE_SERIAL", None)
        (server._stop_event.set if self.old_stop else server._stop_event.clear)()
        self.tmp.cleanup()

    def test_create_job_flags_multipen(self):
        job = server._create_plot_job(TWO_PEN_SVG, server.cfg.copy(), {"x": 0, "y": 0})
        self.assertEqual([p["name"] for p in job["pens"]], ["Black", "Blue"])

    def test_single_pen_job_has_no_pens_key(self):
        job = server._create_plot_job(ONE_PEN_SVG, server.cfg.copy(), {"x": 0, "y": 0})
        self.assertNotIn("pens", job)

    def test_worker_homes_once_per_pen_and_finishes(self):
        job = server._create_plot_job(TWO_PEN_SVG, server.cfg.copy(), {"x": 0, "y": 0})
        server._plot_worker(job)
        done = server._load_plot_job()
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["completed_shapes"], done["total_shapes"])
        self.assertEqual(done["total_shapes"], 3)  # 2 Black + 1 Blue paths
        self.assertEqual(server._FAKE_SERIAL_WRITES.count("$H"), 2)  # re-home per pen

    def test_resume_at_second_pen_skips_first(self):
        job = server._create_plot_job(TWO_PEN_SVG, server.cfg.copy(), {"x": 0, "y": 0})
        # Resume pointed at pen 1 (Blue), path 0 — pen 0 (Black) already done.
        server._checkpoint_plot_job(job, status="stopped", next_copy=0, next_pen=1,
                                    next_path=0)
        server._FAKE_SERIAL_WRITES.clear()
        server._plot_worker(job)
        done = server._load_plot_job()
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["completed_shapes"], done["total_shapes"])
        self.assertEqual(server._FAKE_SERIAL_WRITES.count("$H"), 1)  # only Blue re-homed


if __name__ == "__main__":
    unittest.main()
