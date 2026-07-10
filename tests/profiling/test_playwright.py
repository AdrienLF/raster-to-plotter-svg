import json

import pytest

from profiling.model import Environment
from profiling.playwright import ingest_playwright


def _environment():
    return Environment(
        "TestOS", "1", "x86_64", "CPU", "3.13.2", "abc", "cpu", "chromium",
        None, "Chromium", "browser", "none", "playwright", 0,
    )


def test_ingest_accepts_legacy_and_normalized_rows(tmp_path):
    environment = _environment()
    path = tmp_path / "results.jsonl"
    rows = [
        {"ts": 1, "story": "K9", "duration_ms": 5200},
        {"ts": 2, "story": "BROWSER", "workload": "browser.large_viewport",
         "fixture": "dense-8000", "backend": "chromium", "duration_ms": 75,
         "metrics": {"shapes": 8000}},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    samples = ingest_playwright(path, environment)
    assert [item.workload_id for item in samples] == ["browser.K9", "browser.large_viewport"]
    assert samples[1].metrics["shapes"] == 8000


def test_ingest_rejects_non_numeric_duration(tmp_path):
    path = tmp_path / "results.jsonl"
    path.write_text(json.dumps({"story": "X", "duration_ms": "slow"}) + "\n")
    with pytest.raises(ValueError, match="line 1"):
        ingest_playwright(path, _environment())


def test_ingest_rejects_non_scalar_metric(tmp_path):
    path = tmp_path / "results.jsonl"
    path.write_text(json.dumps(
        {"story": "X", "duration_ms": 5, "metrics": {"bad": [1, 2]}}) + "\n")
    with pytest.raises(ValueError, match="line 1"):
        ingest_playwright(path, _environment())
