"""Self-check for the logfmt formatter and WideEvent. Run: python -m unittest web.test_obslog"""

import logging
import unittest

from web import obslog


def _render(fields):
    rec = logging.LogRecord("plotter", logging.INFO, __file__, 0, "ev.test", (), None)
    rec.fields = fields
    return obslog.LogfmtFormatter().format(rec)


class FormatterTest(unittest.TestCase):
    def test_quoting_and_types(self):
        line = _render({"a": "two words", "b": "x=y", "c": None, "d": 1.23456, "e": True})
        self.assertIn('a="two words"', line)
        self.assertIn('b="x=y"', line)
        self.assertIn("c=-", line)
        self.assertIn("d=1.235", line)
        self.assertIn("e=true", line)

    def test_one_line_with_event_and_timestamp(self):
        line = _render({"a": 1})
        self.assertNotIn("\n", line)
        self.assertIn("ev.test", line)
        self.assertRegex(line, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z INFO ")

    def test_keys_sorted(self):
        line = _render({"zebra": 1, "alpha": 2, "mike": 3})
        self.assertLess(line.index("alpha="), line.index("mike="))
        self.assertLess(line.index("mike="), line.index("zebra="))


class WideEventTest(unittest.TestCase):
    def setUp(self):
        self.records = []
        self.handler = logging.Handler()
        self.handler.emit = lambda r: self.records.append(r)
        self.log = logging.getLogger("plotter")
        self.log.addHandler(self.handler)
        self.log.setLevel(logging.DEBUG)

    def tearDown(self):
        self.log.removeHandler(self.handler)

    def test_stage_accumulation_and_idempotent_emit(self):
        w = obslog.WideEvent("worker.test", "req_abc", logger=self.log)
        with w.time("a"):
            pass
        with w.time("b"):
            pass
        w.emit("success", shapes=3)
        w.emit("success")  # second call is a no-op

        self.assertEqual(len(self.records), 1)
        f = self.records[0].fields
        self.assertEqual(f["request_id"], "req_abc")
        self.assertEqual(f["outcome"], "success")
        self.assertEqual(f["shapes"], 3)
        self.assertIn("stage_a_ms", f)
        self.assertIn("stage_b_ms", f)
        self.assertGreaterEqual(f["duration_ms"], f["stage_a_ms"] + f["stage_b_ms"])

    def test_wrap_progress_times_stages(self):
        forwarded = []
        w = obslog.WideEvent("worker.test", "req_x", logger=self.log)
        op = w.wrap_progress(lambda s, fr: forwarded.append((s, fr)))
        for stage, frac in [("sampling", 0.1), ("styling", 0.6), ("done", 1.0)]:
            op(stage, frac)
        w.emit("success")

        f = self.records[0].fields
        self.assertIn("stage_sampling_ms", f)
        self.assertIn("stage_styling_ms", f)
        self.assertEqual(forwarded, [("sampling", 0.1), ("styling", 0.6), ("done", 1.0)])


if __name__ == "__main__":
    unittest.main()
