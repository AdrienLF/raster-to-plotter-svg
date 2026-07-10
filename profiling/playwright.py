"""Ingest browser performance rows produced by Playwright into profiling samples.

The frontend appends JSONL rows through the ``recordPerf`` fixture. Legacy rows
carry ``{story, pfm?, duration_ms, shapes?}``; enriched browser rows add
``workload``, ``fixture``, ``backend``, and a scalar ``metrics`` map. Both map
into the same normalized :class:`~profiling.model.Sample`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from .model import Environment, Sample

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _scalar(value) -> bool:
    return isinstance(value, (int, float, str, bool))


def _row_to_sample(row: dict, line: int, environment: Environment) -> Sample:
    story = row.get("story")
    workload = row.get("workload")
    if not workload and not story:
        raise ValueError(f"line {line}: row has neither 'workload' nor 'story'")

    workload_id = workload or f"browser.{story}"

    duration = row.get("duration_ms")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool):
        raise ValueError(f"line {line}: duration_ms must be numeric, got {duration!r}")

    metrics = dict(row.get("metrics") or {})
    for key in ("pfm", "shapes"):
        if key in row and key not in metrics:
            metrics[key] = row[key]
    for key, value in metrics.items():
        if not _scalar(value):
            raise ValueError(f"line {line}: metric {key!r} is not scalar: {value!r}")

    return Sample(
        workload_id=workload_id,
        workload_version=1,
        fixture_id=str(row.get("fixture") or "playwright-existing"),
        fixture_checksum="",
        category="browser",
        environment=environment,
        phase="timing",
        sample_kind="warm",
        sample_index=0,
        duration_ms=float(duration),
        python_peak_bytes=None,
        gpu_metrics={},
        metrics=metrics,
        checksum="",
        outcome="success",
        reason=None,
        artifacts={},
    )


def ingest_playwright(path: Path, environment: Environment) -> list[Sample]:
    samples: list[Sample] = []
    for line_number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        text = raw.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_number}: malformed JSON: {exc}") from exc
        samples.append(_row_to_sample(row, line_number, environment))
    return samples


def run_playwright(output_path: Path, full: bool = False) -> Path:
    """Run the browser perf stories and return the JSONL artifact path.

    ``full`` runs the whole e2e suite so every performance story emits a row;
    otherwise only the targeted ``perf:e2e`` set runs.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    env = dict(os.environ)
    env["PLOTTER_PERF_FILE"] = str(output_path)

    script = "e2e" if full else "perf:e2e"
    completed = subprocess.run(
        ["npm", "run", script], cwd=FRONTEND_DIR, env=env, text=True, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Playwright run failed (exit {completed.returncode})")
    if not output_path.is_file():
        raise RuntimeError(f"Playwright produced no perf file at {output_path}")
    return output_path
