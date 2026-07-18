# Performance Profiling Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic CPU/MPS/CUDA/browser profiling suite with warning-only trend reports, then use it to protect and verify the measured SVG circle parsing optimization.

**Architecture:** A new `profiling/` package owns versioned records, environment segmentation, workload registration, isolated measurement, GPU synchronization, Playwright ingestion, reporting, and the CLI. Workloads call existing engine/server interfaces without storing state in user projects; the only production optimization is the native-circle metadata fast path in `web/server.py`.

**Tech Stack:** Python 3.13, standard-library `cProfile`/`pstats`/`tracemalloc`, NumPy/SciPy/Pillow, optional PyTorch 2.6 MPS/CUDA, existing Flask/engine code, pytest, Playwright, GitHub Actions.

## Global Constraints

- Python remains `>=3.13,<3.14`.
- No new runtime dependency or native sampling profiler is added.
- Performance warnings never fail CI; correctness and profiling-infrastructure failures do.
- CPU, MPS, and CUDA measurements are never compared across backend or hardware segments.
- `full` defaults to forced CPU plus every available production accelerator.
- Every GPU timed region synchronizes immediately before and after measurement.
- A requested GPU run that falls back to NumPy is an error.
- Runtime artifacts live under ignored `artifacts/profiling/`; only explicit named baselines are committed.
- Baselines are replaced only by an explicit command; CI never updates them.
- No machine-specific wall-time threshold is added to unit tests.
- The PlotterForge UI and artist-facing workflow remain unchanged.
- MPS reports synchronized timing and boundary memory; it does not claim CUDA-style kernel traces.

## File Structure

- Create `profiling/__init__.py`: package version and public model exports.
- Create `profiling/model.py`: environment, sample, run, aggregate, and comparison records plus JSON serialization.
- Create `profiling/environment.py`: stable machine/runtime/backend identity collection.
- Create `profiling/workload.py`: workload protocol, registry, fixture checksums, and output metrics.
- Create `profiling/gpu.py`: backend selection, synchronization, memory snapshots, and CUDA/MPS diagnostics.
- Create `profiling/worker.py`: one isolated workload/backend measurement process.
- Create `profiling/runner.py`: profile selection, worker orchestration, temp-home isolation, and result collection.
- Create `profiling/report.py`: aggregation, baseline comparison, Markdown, JSON, and CI warnings.
- Create `profiling/playwright.py`: conversion of existing browser JSONL rows to normalized samples.
- Create `profiling/cli.py`: argument parsing and command dispatch.
- Create `profiling/workloads/__init__.py`: idempotent workload registration.
- Create `profiling/workloads/primitives.py`: acceleration, ordering, chaining, and clipping workloads.
- Create `profiling/workloads/creative.py`: dynamically discovered PFM and generator workloads.
- Create `profiling/workloads/pipeline.py`: SVG, composition, pen-split, and plot-preparation workloads.
- Create `tools/profile_suite.py`: repository-local executable entry point.
- Create `tests/profiling/`: focused tests mirroring each package module.
- Create `frontend/e2e/perf-browser.spec.ts`: boot and large-viewport browser timings.
- Modify `frontend/e2e/fixtures.ts`: enrich performance rows without breaking existing stories.
- Modify `web/server.py:736-753`: direct resolved-circle metadata fast path with fallback.
- Create `tests/test_svg_circle_fastpath.py`: structural and geometric optimization regressions.
- Create `docs/profiling.md`: local, GPU, artifact, and baseline guide.
- Modify `README.md:172-185`, `FEATURES.md`, and `.gitignore` for discoverability and artifact hygiene.
- Create `.github/workflows/profile.yml`: warning-only CPU/browser profiling workflow.

---

### Task 1: Versioned result model and environment segmentation

**Files:**
- Create: `profiling/__init__.py`
- Create: `profiling/model.py`
- Create: `profiling/environment.py`
- Create: `tests/profiling/__init__.py`
- Create: `tests/profiling/test_model.py`
- Create: `tests/profiling/test_environment.py`

**Interfaces:**
- Produces: `Environment`, `Sample`, `RunResult`, `Aggregate`, `Comparison`, `SCHEMA_VERSION`.
- Produces: `collect_environment(requested_backend, actual_backend, workload_meta, accelerator_meta) -> Environment`.
- `Environment.segment_key()` is the sole compatibility key consumed by baseline comparison.
- JSON uses `RunResult.to_dict()` and `RunResult.from_dict(data)`; unknown schema versions raise `ValueError`.

- [ ] **Step 1: Write failing serialization and segmentation tests**

```python
# tests/profiling/test_model.py
import pytest

from profiling.model import Environment, RunResult, Sample


def environment(**changes):
    values = dict(
        os_name="Darwin", os_version="15.5", machine="arm64", processor="Apple M2 Max",
        python="3.13.2", commit="abc123", requested_backend="gpu",
        actual_backend="torch-mps", torch_version="2.6.0", device="Apple M2 Max",
        runtime="mps", dtype="float32", problem_size="points=8000,sites=1000", tile=65536,
    )
    values.update(changes)
    return Environment(**values)


def test_run_result_round_trips_nested_samples():
    sample = Sample(
        workload_id="svg.parse_dense_circles", workload_version=1,
        fixture_id="dense-circles", fixture_checksum="sha256:abc",
        category="pipeline", environment=environment(), phase="timing",
        sample_kind="warm", sample_index=0, duration_ms=12.5,
        python_peak_bytes=None, gpu_metrics={}, metrics={"paths": 8000},
        checksum="sha256:def", outcome="success", reason=None, artifacts={},
    )
    run = RunResult.new(command="quick", commit="abc123", samples=[sample])
    restored = RunResult.from_dict(run.to_dict())
    assert restored == run


def test_unknown_schema_version_is_rejected():
    run = RunResult.new(command="quick", commit="abc123", samples=[]).to_dict()
    run["schema_version"] = 999
    with pytest.raises(ValueError, match="schema version"):
        RunResult.from_dict(run)


def test_segment_key_changes_for_backend_hardware_or_problem_size():
    base = environment()
    assert base.segment_key() != environment(actual_backend="numpy").segment_key()
    assert base.segment_key() != environment(device="Apple M3 Max").segment_key()
    assert base.segment_key() != environment(problem_size="points=4000,sites=1000").segment_key()
```

```python
# tests/profiling/test_environment.py
from profiling.environment import collect_environment


def test_collect_environment_includes_explicit_workload_and_accelerator_metadata(monkeypatch):
    monkeypatch.setattr("profiling.environment._git_commit", lambda: "deadbeef")
    env = collect_environment(
        requested_backend="cpu", actual_backend="numpy",
        workload_meta={"dtype": "float32", "problem_size": "n=8", "tile": 0},
        accelerator_meta={"torch_version": None, "device": "CPU", "runtime": "numpy"},
    )
    assert env.commit == "deadbeef"
    assert env.actual_backend == "numpy"
    assert env.problem_size == "n=8"
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run --frozen pytest tests/profiling/test_model.py tests/profiling/test_environment.py -q`

Expected: collection fails because `profiling.model` and `profiling.environment` do not exist.

- [ ] **Step 3: Implement the records and explicit compatibility key**

```python
# profiling/model.py
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import uuid

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Environment:
    os_name: str
    os_version: str
    machine: str
    processor: str
    python: str
    commit: str
    requested_backend: str
    actual_backend: str
    torch_version: str | None
    device: str
    runtime: str
    dtype: str
    problem_size: str
    tile: int

    def segment_key(self) -> str:
        data = {
            "os": [self.os_name, self.os_version], "machine": self.machine,
            "processor": self.processor, "python": self.python,
            "backend": self.actual_backend, "torch": self.torch_version,
            "device": self.device, "runtime": self.runtime, "dtype": self.dtype,
            "problem_size": self.problem_size, "tile": self.tile,
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Sample:
    workload_id: str
    workload_version: int
    fixture_id: str
    fixture_checksum: str
    category: str
    environment: Environment
    phase: str
    sample_kind: str
    sample_index: int
    duration_ms: float
    python_peak_bytes: int | None
    gpu_metrics: dict[str, int]
    metrics: dict[str, int | float | str | bool]
    checksum: str
    outcome: str
    reason: str | None
    artifacts: dict[str, str]


@dataclass(frozen=True)
class RunResult:
    schema_version: int
    run_id: str
    timestamp_utc: str
    command: str
    commit: str
    samples: list[Sample] = field(default_factory=list)

    @classmethod
    def new(cls, command: str, commit: str, samples: list[Sample]) -> "RunResult":
        return cls(SCHEMA_VERSION, uuid.uuid4().hex, datetime.now(timezone.utc).isoformat(),
                   command, commit, samples)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RunResult":
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported profiling schema version: {data.get('schema_version')}")
        samples = []
        for raw in data.get("samples", []):
            item = dict(raw)
            item["environment"] = Environment(**item["environment"])
            samples.append(Sample(**item))
        return cls(data["schema_version"], data["run_id"], data["timestamp_utc"],
                   data["command"], data["commit"], samples)


@dataclass(frozen=True)
class Aggregate:
    workload_id: str
    workload_version: int
    fixture_checksum: str
    segment_key: str
    count: int
    samples_ms: tuple[float, ...]
    minimum_ms: float
    median_ms: float
    p90_ms: float
    maximum_ms: float
    peak_python_bytes: int | None
    peak_gpu_bytes: int | None


@dataclass(frozen=True)
class Comparison:
    status: str
    delta_ms: float | None
    delta_ratio: float | None
    reason: str | None
```

```python
# profiling/environment.py
from __future__ import annotations

import platform
import subprocess
import sys

from .model import Environment


def _git_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], text=True,
                            capture_output=True, check=False)
    return result.stdout.strip() or "unknown"


def collect_environment(requested_backend: str, actual_backend: str,
                        workload_meta: dict, accelerator_meta: dict) -> Environment:
    return Environment(
        os_name=platform.system(), os_version=platform.release(), machine=platform.machine(),
        processor=platform.processor() or platform.machine(),
        python=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        commit=_git_commit(), requested_backend=requested_backend,
        actual_backend=actual_backend, torch_version=accelerator_meta.get("torch_version"),
        device=str(accelerator_meta.get("device", "CPU")),
        runtime=str(accelerator_meta.get("runtime", actual_backend)),
        dtype=str(workload_meta.get("dtype", "none")),
        problem_size=str(workload_meta.get("problem_size", "default")),
        tile=int(workload_meta.get("tile", 0) or 0),
    )
```

- [ ] **Step 4: Add `profiling/__init__.py` exports and verify GREEN**

```python
from .model import Aggregate, Comparison, Environment, RunResult, Sample, SCHEMA_VERSION

__all__ = ["Aggregate", "Comparison", "Environment", "RunResult", "Sample", "SCHEMA_VERSION"]
```

Run: `uv run --frozen pytest tests/profiling/test_model.py tests/profiling/test_environment.py -q`

Expected: all focused tests pass.

- [ ] **Step 5: Commit the result model**

```bash
git add profiling tests/profiling
git commit -m "feat: add profiling result model"
```

---

### Task 2: Workload contract, registry, and deterministic fixture checksums

**Files:**
- Create: `profiling/workload.py`
- Create: `tests/profiling/test_workload.py`

**Interfaces:**
- Produces: `Workload`, `WorkloadCase`, `WorkloadOutput`.
- Produces: `register(workload)`, `get_workload(workload_id)`, `iter_workloads(category=None)`.
- Produces: `stable_checksum(value, precision=6) -> str`.
- `Workload.prepare()` and `Workload.run(case)` are never timed together; validation is always outside the timed region.
- `Workload.metadata["cold_group"]` names the isolated startup group or is an empty string when no cold measurement applies.

- [ ] **Step 1: Write failing registry, checksum, and validation tests**

```python
import pytest

from profiling.workload import (
    Workload, WorkloadCase, WorkloadOutput, get_workload, register,
    reset_registry_for_tests, stable_checksum,
)


def make_workload(workload_id="test.one"):
    return Workload(
        id=workload_id, version=1, category="test", fixture_id="fixture",
        quick=True, backends=("cpu",), warning_floor_ms=1.0,
        metadata={"dtype": "none", "problem_size": "one", "tile": 0},
        prepare=lambda: WorkloadCase(value=[(1.23456789, 2.0)], fixture_checksum="sha256:x"),
        run=lambda case: WorkloadOutput({"items": len(case.value)}, stable_checksum(case.value)),
        validate=lambda output: None,
    )


def test_registry_rejects_duplicate_ids():
    reset_registry_for_tests()
    register(make_workload())
    with pytest.raises(ValueError, match="Duplicate workload"):
        register(make_workload())
    assert get_workload("test.one").version == 1


def test_stable_checksum_quantizes_float_noise():
    assert stable_checksum([(1.00000001, 2.0)]) == stable_checksum([(1.00000002, 2.0)])
    assert stable_checksum([(1.0001, 2.0)]) != stable_checksum([(1.0002, 2.0)])


def test_workload_output_metrics_are_scalar():
    with pytest.raises(TypeError, match="scalar"):
        WorkloadOutput({"bad": [1, 2]}, "sha256:x")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run --frozen pytest tests/profiling/test_workload.py -q`

Expected: collection fails because `profiling.workload` does not exist.

- [ ] **Step 3: Implement the immutable contract and idempotent registry**

```python
# profiling/workload.py
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Callable

Scalar = int | float | str | bool


def _normalized(value, precision):
    if isinstance(value, float):
        return round(value, precision)
    if isinstance(value, dict):
        return {str(k): _normalized(v, precision) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalized(v, precision) for v in value]
    return value


def stable_checksum(value, precision: int = 6) -> str:
    payload = json.dumps(_normalized(value, precision), sort_keys=True,
                         separators=(",", ":"), default=str).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class WorkloadCase:
    value: object
    fixture_checksum: str


@dataclass(frozen=True)
class WorkloadOutput:
    metrics: dict[str, Scalar]
    checksum: str

    def __post_init__(self):
        if not all(isinstance(v, (int, float, str, bool)) for v in self.metrics.values()):
            raise TypeError("Workload metrics must be scalar")


@dataclass(frozen=True)
class Workload:
    id: str
    version: int
    category: str
    fixture_id: str
    quick: bool
    backends: tuple[str, ...]
    warning_floor_ms: float
    metadata: dict[str, Scalar]
    prepare: Callable[[], WorkloadCase]
    run: Callable[[WorkloadCase], WorkloadOutput]
    validate: Callable[[WorkloadOutput], None]


_REGISTRY: dict[str, Workload] = {}


def register(workload: Workload) -> Workload:
    if workload.id in _REGISTRY:
        raise ValueError(f"Duplicate workload: {workload.id}")
    _REGISTRY[workload.id] = workload
    return workload


def get_workload(workload_id: str) -> Workload:
    return _REGISTRY[workload_id]


def iter_workloads(category: str | None = None) -> list[Workload]:
    values = sorted(_REGISTRY.values(), key=lambda item: item.id)
    return [item for item in values if category is None or item.category == category]


def reset_registry_for_tests() -> None:
    _REGISTRY.clear()
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `uv run --frozen pytest tests/profiling/test_workload.py -q`

Expected: all focused tests pass.

- [ ] **Step 5: Commit the workload contract**

```bash
git add profiling/workload.py tests/profiling/test_workload.py
git commit -m "feat: add profiling workload registry"
```

---

### Task 3: Isolated timing, CPU profile, and Python-memory runner

**Files:**
- Create: `profiling/worker.py`
- Create: `profiling/runner.py`
- Create: `tests/profiling/test_worker.py`
- Create: `tests/profiling/test_runner.py`

**Interfaces:**
- Produces: `WorkerRequest`, `execute_workload(workload, environment, warmups, repeats, diagnostics, artifact_dir, requested_backend="cpu") -> list[Sample]`, and `execute_request(request, artifact_dir) -> list[Sample]`.
- Produces: `RunConfig`, `run_suite(workload_ids, config) -> RunResult`.
- `RunConfig.mode` is `quick`, `full`, or `diagnose`.
- Each workload/backend group runs in `python -m profiling.worker` with an isolated temporary `HOME`/`USERPROFILE`.

- [ ] **Step 1: Write failing measurement and error-isolation tests**

```python
# tests/profiling/test_worker.py
from pathlib import Path

from profiling.model import Environment
from profiling.worker import execute_workload
from profiling.workload import Workload, WorkloadCase, WorkloadOutput


ENV = Environment("TestOS", "1", "x86_64", "CPU", "3.13.2", "abc", "cpu",
                  "numpy", None, "CPU", "numpy", "none", "one", 0)


def test_execute_workload_separates_warmup_timing_profile_and_memory(tmp_path: Path):
    calls = []
    workload = Workload(
        "test.counter", 1, "test", "counter", True, ("cpu",), 1.0,
        {"dtype": "none", "problem_size": "one", "tile": 0},
        lambda: WorkloadCase(3, "sha256:fixture"),
        lambda case: (calls.append(case.value) or WorkloadOutput({"value": case.value}, "sha256:out")),
        lambda output: None,
    )
    samples = execute_workload(workload, ENV, warmups=1, repeats=3,
                               diagnostics=True, artifact_dir=tmp_path)
    timing = [item for item in samples if item.phase == "timing"]
    assert len(timing) == 3
    assert all(item.sample_kind == "warm" for item in timing)
    assert any(item.phase == "memory" and item.python_peak_bytes is not None for item in samples)
    assert (tmp_path / "test.counter.prof").is_file()
    assert len(calls) == 6


def test_execute_workload_converts_validation_failure_to_error_sample(tmp_path: Path):
    workload = Workload(
        "test.invalid", 1, "test", "invalid", True, ("cpu",), 1.0,
        {"dtype": "none", "problem_size": "one", "tile": 0},
        lambda: WorkloadCase(1, "sha256:fixture"),
        lambda case: WorkloadOutput({"value": case.value}, "sha256:bad"),
        lambda output: (_ for _ in ()).throw(ValueError("checksum changed")),
    )
    samples = execute_workload(workload, ENV, 0, 1, False, tmp_path)
    assert samples[0].outcome == "error"
    assert "checksum changed" in samples[0].reason
```

```python
# tests/profiling/test_runner.py
from profiling.runner import RunConfig, selected_counts


def test_profile_modes_have_explicit_counts():
    assert selected_counts(RunConfig(mode="quick")) == (1, 3)
    assert selected_counts(RunConfig(mode="full")) == (2, 10)
    assert selected_counts(RunConfig(mode="diagnose")) == (1, 5)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run --frozen pytest tests/profiling/test_worker.py tests/profiling/test_runner.py -q`

Expected: collection fails because the runner modules do not exist.

- [ ] **Step 3: Implement in-process measurement with diagnostics outside timing samples**

Implement these exact rules in `profiling/worker.py`:

```python
@dataclass(frozen=True)
class WorkerRequest:
    workload_id: str
    requested_backend: str
    warmups: int
    repeats: int
    diagnostics: bool
    sample_kind: str = "warm"


def _time_once(workload, case):
    start = perf_counter_ns()
    output = workload.run(case)
    duration_ms = (perf_counter_ns() - start) / 1_000_000
    workload.validate(output)
    return output, duration_ms


def execute_workload(workload, environment, warmups, repeats, diagnostics, artifact_dir):
    case = workload.prepare()
    for _ in range(warmups):
        output = workload.run(case)
        workload.validate(output)
    samples = []
    for index in range(repeats):
        try:
            output, duration_ms = _time_once(workload, case)
            samples.append(_sample(workload, case, environment, "timing", "warm", index,
                                   duration_ms, output, None, {}, {}))
        except Exception as exc:
            samples.append(_error_sample(workload, case, environment, "timing", index, exc))
            break
    if diagnostics and not any(item.outcome == "error" for item in samples):
        profile_path = artifact_dir / f"{workload.id}.prof"
        profiler = cProfile.Profile()
        output = profiler.runcall(workload.run, case)
        workload.validate(output)
        profiler.dump_stats(profile_path)
        tracemalloc.start()
        start = perf_counter_ns()
        output = workload.run(case)
        duration_ms = (perf_counter_ns() - start) / 1_000_000
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        workload.validate(output)
        samples.append(_sample(workload, case, environment, "memory", "warm", 0,
                               duration_ms, output, peak, {},
                               {"cpu_profile": str(profile_path)}))
    return samples
```

`_sample()` and `_error_sample()` must populate every `Sample` field defined in Task 1. The error sample uses `duration_ms=0.0`, `outcome="error"`, and `reason=f"{type(exc).__name__}: {exc}"`.

- [ ] **Step 4: Implement subprocess orchestration and isolated homes**

Implement this configuration contract in `profiling/runner.py`:

```python
@dataclass(frozen=True)
class RunConfig:
    mode: str
    backend: str = "auto"
    repeat: int | None = None
    categories: tuple[str, ...] = ()
    excluded_categories: tuple[str, ...] = ()
    output_dir: Path = Path("artifacts/profiling")


def selected_counts(config: RunConfig) -> tuple[int, int]:
    defaults = {"quick": (1, 3), "full": (2, 10), "diagnose": (1, 5)}
    warmups, repeats = defaults[config.mode]
    return warmups, config.repeat if config.repeat is not None else repeats
```

Implement request/response JSON files and `run_suite()` in `profiling/runner.py`. Use `tempfile.TemporaryDirectory(prefix="plotter-profile-")`, set `HOME`, `USERPROFILE`, and `PLOTTER_LOG_FILE=0`, and invoke:

```python
command = [sys.executable, "-m", "profiling.worker", str(request_path), str(response_path)]
completed = subprocess.run(command, cwd=repo_root, env=env, text=True,
                           capture_output=True, check=False)
```

Continue after a non-zero worker exit by adding an error sample for that workload. Build `RunResult.new(config.mode, commit, samples)` only after every selected workload/backend group has been attempted.

For `full`, launch one additional fresh worker with zero warmups, one repeat, and `sample_kind="cold"` for the first workload in each non-empty `metadata["cold_group"]`. Normal workers still produce the ten warmed samples. Expand backend `all` to CPU for every CPU-capable workload and GPU only for workloads declaring GPU support when an accelerator is available. An explicitly requested unavailable GPU becomes an error sample.

Add a `profiling.worker.main(argv=None) -> int` that loads `WorkerRequest` JSON, calls `profiling.workloads.register_all()`, enters `backend_session()`, executes the requested workload, and atomically writes a JSON list of samples. End `profiling/worker.py` with `raise SystemExit(main())` under the standard `__main__` guard.

- [ ] **Step 5: Run focused and package tests and verify GREEN**

Run: `uv run --frozen pytest tests/profiling/test_worker.py tests/profiling/test_runner.py -q`

Expected: all focused tests pass, including creation of a readable `.prof` file and a non-zero Python peak.

- [ ] **Step 6: Commit the CPU runner**

```bash
git add profiling/worker.py profiling/runner.py tests/profiling/test_worker.py tests/profiling/test_runner.py
git commit -m "feat: add isolated profiling runner"
```

---

### Task 4: Synchronized MPS/CUDA backend adapter and diagnostics

**Files:**
- Create: `profiling/gpu.py`
- Create: `tests/profiling/test_gpu.py`
- Modify: `profiling/worker.py`

**Interfaces:**
- Produces: `backend_session(requested_backend) -> context manager[BackendSession]`.
- `BackendSession` exposes `actual_backend`, `metadata()`, `synchronize()`, `reset_usage()`, `reset_memory()`, `memory_snapshot()`, `diagnostic_trace(path)`, and `assert_gpu_used()`.
- `gpu` requires an active MPS/CUDA device; `cpu` forces NumPy; `auto` preserves production selection.

- [ ] **Step 1: Write failing synchronization, memory, and fallback tests**

```python
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from profiling.model import Environment
from profiling.gpu import BackendUnavailable, backend_session
from profiling.worker import execute_workload
from profiling.workload import Workload, WorkloadCase, WorkloadOutput


ENV = Environment("TestOS", "1", "x86_64", "CPU", "3.13.2", "abc", "gpu",
                  "torch-mps", "2.6.0", "Test GPU", "mps", "none", "one", 0)


def make_test_workload(events):
    return Workload(
        "test.gpu", 1, "test", "gpu", True, ("gpu",), 1.0,
        {"dtype": "none", "problem_size": "one", "tile": 0},
        lambda: WorkloadCase(1, "sha256:fixture"),
        lambda case: (events.append("run") or WorkloadOutput({"value": case.value}, "sha256:out")),
        lambda output: None,
    )


class FakeAccel:
    def __init__(self, device):
        self.DEVICE = device

    def backend_name(self):
        return "numpy" if self.DEVICE is None else f"torch-{self.DEVICE.type}"


class Device:
    def __init__(self, kind):
        self.type = kind


def test_cpu_session_forces_numpy_and_restores_device():
    accel = FakeAccel(Device("mps"))
    with backend_session("cpu", accel_module=accel, torch_module=None) as session:
        assert session.actual_backend == "numpy"
        assert accel.DEVICE is None
    assert accel.DEVICE.type == "mps"


def test_requested_gpu_rejects_missing_device():
    accel = FakeAccel(None)
    with pytest.raises(BackendUnavailable, match="GPU requested"):
        with backend_session("gpu", accel_module=accel, torch_module=None):
            pass


def test_worker_synchronizes_on_both_sides_of_timed_call(monkeypatch, tmp_path):
    events = []
    session = SimpleNamespace(actual_backend="torch-mps", synchronize=lambda: events.append("sync"),
                              reset_usage=lambda: None, reset_memory=lambda: None, memory_snapshot=lambda: {},
                              metadata=lambda: {}, diagnostic_trace=nullcontext,
                              assert_gpu_used=lambda: None)
    monkeypatch.setattr("profiling.worker.backend_session", lambda requested: nullcontext(session))
    workload = make_test_workload(events)
    execute_workload(workload, ENV, 0, 1, False, tmp_path, requested_backend="gpu")
    assert events == ["sync", "run", "sync"]


def test_requested_gpu_rejects_a_workload_that_never_dispatches_gpu(monkeypatch, tmp_path):
    session = SimpleNamespace(
        actual_backend="torch-mps", synchronize=lambda: None, reset_memory=lambda: None,
        reset_usage=lambda: None, memory_snapshot=lambda: {}, metadata=lambda: {},
        diagnostic_trace=nullcontext,
        assert_gpu_used=lambda: (_ for _ in ()).throw(BackendUnavailable("GPU workload used no GPU primitive")),
    )
    monkeypatch.setattr("profiling.worker.backend_session", lambda requested: nullcontext(session))
    samples = execute_workload(make_test_workload([]), ENV, 0, 1, False, tmp_path,
                               requested_backend="gpu")
    assert samples[0].outcome == "error"
    assert "used no GPU primitive" in samples[0].reason
```

- [ ] **Step 2: Run the GPU-adapter tests and verify RED**

Run: `uv run --frozen pytest tests/profiling/test_gpu.py -q`

Expected: collection fails because `profiling.gpu` does not exist.

- [ ] **Step 3: Implement backend selection and honest memory metrics**

Implement `BackendSession` with these backend-specific operations:

```python
def synchronize(self):
    if self.kind == "cuda":
        self.torch.cuda.synchronize()
    elif self.kind == "mps":
        self.torch.mps.synchronize()


def reset_memory(self):
    if self.kind == "cuda":
        self.torch.cuda.reset_peak_memory_stats()


def memory_snapshot(self):
    self.synchronize()
    if self.kind == "cuda":
        return {
            "allocated_bytes": int(self.torch.cuda.memory_allocated()),
            "reserved_bytes": int(self.torch.cuda.memory_reserved()),
            "peak_allocated_bytes": int(self.torch.cuda.max_memory_allocated()),
            "peak_reserved_bytes": int(self.torch.cuda.max_memory_reserved()),
        }
    if self.kind == "mps":
        return {
            "allocated_bytes": int(self.torch.mps.current_allocated_memory()),
            "driver_allocated_bytes": int(self.torch.mps.driver_allocated_memory()),
        }
    return {}
```

CUDA `diagnostic_trace(path)` uses `torch.profiler.profile` with CPU and CUDA activities and exports a Chrome trace. MPS uses `torch.mps.profiler.profile()` and writes a JSON sidecar recording that signposts require Instruments. CPU uses `contextlib.nullcontext()`.

`metadata()` records `torch.cuda.get_device_name()`, compute capability, and `torch.version.cuda` for CUDA. For MPS it records `sysctl -n machdep.cpu.brand_string` and `sysctl -n hw.model` with `platform.machine()` fallbacks, plus the macOS and PyTorch versions.

To prove actual dispatch, the session installs process-local wrappers around `engine.accel._assign_nearest_torch` and `_greedy_order_torch` and a temporary handler for `plotter.engine.accel`. `reset_usage()` clears per-measurement counters and captured fallbacks. `assert_gpu_used()` fails when no wrapped GPU primitive ran or when an `accel.gpu_fallback` warning was emitted. Restore wrappers and logging handlers on context exit.

- [ ] **Step 4: Wrap every timed and diagnostic workload call**

Change `_time_once()` to call `session.reset_usage()`, synchronize, start the clock, run the workload, synchronize again, then stop the clock. For requested-GPU workloads, call `session.assert_gpu_used()` before accepting the output. Record `session.memory_snapshot()` only in the separate memory phase. Wrap the diagnostic run in `session.diagnostic_trace(trace_path)` and synchronize on both sides. Build the `Environment` after entering the session so `actual_backend` cannot be stale.

- [ ] **Step 5: Run focused tests and a conditional real backend smoke**

Run: `uv run --frozen pytest tests/profiling/test_gpu.py tests/profiling/test_worker.py -q`

Expected: fake-backend tests pass; the real-MPS/CUDA smoke is skipped with a reason when no accelerator is visible.

- [ ] **Step 6: Commit the GPU adapter**

```bash
git add profiling/gpu.py profiling/worker.py tests/profiling/test_gpu.py tests/profiling/test_worker.py
git commit -m "feat: profile MPS and CUDA workloads"
```

---

### Task 5: Aggregation, named baselines, Markdown reports, and exit policy

**Files:**
- Create: `profiling/report.py`
- Create: `tests/profiling/test_report.py`

**Interfaces:**
- Produces: `aggregate_samples(samples) -> list[Aggregate]`.
- Produces: `compare_aggregate(current, baseline, warning_floor_ms) -> Comparison`.
- Produces: `write_report(run, output_dir, baseline=None) -> list[Comparison]`.
- Produces: `update_baseline(results_path, baseline_path) -> None`.
- Only `phase="timing"`, `sample_kind="warm"`, and `outcome="success"` contribute to latency aggregates.

- [ ] **Step 1: Write failing percentile, warning, and incomparable tests**

```python
from profiling.model import Aggregate
from profiling.report import compare_aggregate, nearest_rank, summarize_values


def aggregate(workload_id, segment, median, samples):
    ordered = tuple(sorted(float(value) for value in samples))
    return Aggregate(
        workload_id=workload_id, workload_version=1, fixture_checksum="sha256:fixture",
        segment_key=segment, count=len(ordered), samples_ms=ordered,
        minimum_ms=ordered[0], median_ms=float(median), p90_ms=ordered[-1],
        maximum_ms=ordered[-1], peak_python_bytes=None, peak_gpu_bytes=None,
    )


def test_nearest_rank_and_summary_are_deterministic():
    values = [10, 20, 30, 40, 50]
    assert nearest_rank(values, 0.9) == 50
    assert summarize_values(values) == (10, 30, 50, 50)


def test_warning_requires_ratio_floor_and_sample_majority():
    baseline = aggregate("w", "segment", median=100, samples=[90, 100, 110, 100])
    warned = aggregate("w", "segment", median=130, samples=[125, 126, 130, 139])
    assert compare_aggregate(warned, baseline, 25).status == "warning"
    too_small = aggregate("w", "segment", median=124, samples=[123, 124, 125, 126])
    assert compare_aggregate(too_small, baseline, 25).status == "stable"
    noisy = aggregate("w", "segment", median=130, samples=[90, 99, 130, 150])
    assert compare_aggregate(noisy, baseline, 25).status == "stable"


def test_segment_mismatch_is_incomparable():
    current = aggregate("w", "mps-a", median=130, samples=[130])
    baseline = aggregate("w", "cuda-b", median=100, samples=[100])
    result = compare_aggregate(current, baseline, 25)
    assert result.status == "incomparable"
```

- [ ] **Step 2: Run report tests and verify RED**

Run: `uv run --frozen pytest tests/profiling/test_report.py -q`

Expected: collection fails because `profiling.report` does not exist.

- [ ] **Step 3: Implement nearest-rank aggregation and the exact warning rule**

Implement nearest-rank p90 as `sorted_values[max(0, ceil(0.9 * n) - 1)]`. Compare only exact workload ID/version, fixture checksum, and `Environment.segment_key()` matches. Return `warning` only when median ratio is greater than `1.20`, absolute delta is at least the workload floor, and at least `ceil(0.75 * current.count)` current samples exceed the baseline median.

- [ ] **Step 4: Implement atomic JSON/Markdown output and explicit baseline update**

`write_report()` writes `results.json` through a sibling temporary file followed by `Path.replace()`. `summary.md` contains environment, workload, count, min, median, p90, max, memory, baseline delta, and status columns. When a sample links a `.prof` artifact, load it with `pstats.Stats`, sort by cumulative time, and append the top 20 functions in a fenced text section. Emit GitHub annotations only when `GITHUB_ACTIONS=true`:

```python
print(f"::warning title=Performance regression::{workload_id} median {median_ms:.1f} ms "
      f"({delta_ratio:+.1%}, {delta_ms:+.1f} ms)")
```

`update_baseline()` rejects any run containing an error sample and writes only after validating schema and internal segment consistency.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `uv run --frozen pytest tests/profiling/test_report.py -q`

Expected: all report tests pass and temporary-file tests leave no partial result on failure.

- [ ] **Step 6: Commit reporting and baselines**

```bash
git add profiling/report.py tests/profiling/test_report.py
git commit -m "feat: add profiling trend reports"
```

---

### Task 6: Primitive, creative, SVG, composition, and plot workloads

**Files:**
- Create: `profiling/workloads/__init__.py`
- Create: `profiling/workloads/primitives.py`
- Create: `profiling/workloads/creative.py`
- Create: `profiling/workloads/pipeline.py`
- Create: `tests/profiling/test_workloads.py`

**Interfaces:**
- Produces: `register_all()`, which is idempotent and registers every workload exactly once.
- Workload IDs use `primitive.*`, `pfm.<registry-id>`, `generator.<registry-id>`, and `pipeline.*`.
- Every workload returns at least one size/count metric plus a stable checksum.

- [ ] **Step 1: Write failing discovery and dense-circle invariant tests**

```python
from engine.generate import GENERATORS
from engine.pfm import REGISTRY
from profiling.workload import get_workload, iter_workloads, reset_registry_for_tests
from profiling.workloads import register_all


def test_full_registry_contains_every_pfm_and_generator():
    reset_registry_for_tests()
    register_all()
    ids = {item.id for item in iter_workloads()}
    assert {f"pfm.{name}" for name in REGISTRY} <= ids
    assert {f"generator.{name}" for name in GENERATORS} <= ids


def test_dense_circle_fixture_has_stable_size_and_output():
    reset_registry_for_tests()
    register_all()
    workload = get_workload("pipeline.svg_dense_circles")
    case = workload.prepare()
    output = workload.run(case)
    workload.validate(output)
    assert output.metrics["paths"] == 8000
    assert output.metrics["svg_bytes"] > 400_000


def test_every_quick_workload_has_a_valid_cpu_result():
    reset_registry_for_tests()
    register_all()
    for workload in (item for item in iter_workloads() if item.quick and "cpu" in item.backends):
        output = workload.run(workload.prepare())
        workload.validate(output)
```

- [ ] **Step 2: Run workload tests and verify RED**

Run: `HOME=/tmp/plotter-profile-tests PLOTTER_LOG_FILE=0 uv run --frozen pytest tests/profiling/test_workloads.py -q`

Expected: collection fails because `profiling.workloads` does not exist.

- [ ] **Step 3: Implement deterministic primitive and pipeline fixtures**

Use fixed NumPy RNG seed `20260710`. The accelerated nearest-site workload must satisfy `points * sites > 1_000_000`. The dense SVG fixture is generated in memory with exactly 8,000 circles inside one SVG group. Pipeline workloads call the real `web.server.svg_to_polylines`, `_reorder`, `_estimate_polylines`, `engine.composition.compose_visible_svg`, and `engine.svg_io.split_svg_by_pen` interfaces.

Validate exact path/shape counts and checksum coordinates after six-decimal quantization. Keep validation outside the timed callable.

- [ ] **Step 4: Dynamically register all PFMs and generators**

For each PFM, prepare the checked-in `frontend/e2e/assets/sample.png`, `DrawingArea()`, `DrawingSet()`, default validated parameters, and seed `20260710`. The timed call is `pfm.run(image, area, drawing_set, params, seed=20260710)`; output metrics are drawing total, SVG bytes, and path length. For each generator, use its `normalize` function or schema validation, run with seed `20260710`, and record line and point counts.

Register `voronoi_*` and `lbg_*` workloads for `("cpu", "gpu")` because they call the accelerated nearest-site primitive at the chosen fixture size. Register other PFMs/generators as CPU workloads unless their production code actually calls an accelerated primitive. Register the large nearest-site and 10,000-path ordering primitives for both CPU and GPU. This prevents a GPU-labeled result for code that never dispatched a GPU operation.

Use an explicit small deterministic override map only when a default is unsuitable for repeatable profiling:

```python
PFM_OVERRIDES = {
    "differential_growth": {"iterations": 20},
    "sketch_lines": {"line_max_limit": 500},
    "sketch_curves": {"line_max_limit": 500},
    "sketch_squares": {"line_max_limit": 500},
    "circle_packing": {"attempts": 1000},
}
```

If a registry ID lacks a successful result, `full` fails; it may not silently skip that PFM/generator.

- [ ] **Step 5: Run the workload matrix tests and verify GREEN**

Run: `HOME=/tmp/plotter-profile-tests PLOTTER_LOG_FILE=0 uv run --frozen pytest tests/profiling/test_workloads.py -q`

Expected: all discovery and quick-workload tests pass on CPU.

- [ ] **Step 6: Commit the workload matrix**

```bash
git add profiling/workloads tests/profiling/test_workloads.py
git commit -m "feat: add profiling workload matrix"
```

---

### Task 7: Playwright ingestion and browser performance stories

**Files:**
- Create: `profiling/playwright.py`
- Create: `tests/profiling/test_playwright.py`
- Modify: `frontend/e2e/fixtures.ts:228-238`
- Create: `frontend/e2e/perf-browser.spec.ts`

**Interfaces:**
- Produces: `ingest_playwright(path, environment) -> list[Sample]`.
- Produces: `run_playwright(output_path, full=False) -> Path`.
- Existing `{story, pfm, duration_ms, shapes}` rows remain accepted.
- New browser rows add `workload`, `fixture`, `backend`, and scalar `metrics`.

- [ ] **Step 1: Write failing legacy/new-row normalization tests**

```python
import json

from profiling.model import Environment
from profiling.playwright import ingest_playwright


def test_ingest_accepts_legacy_and_normalized_rows(tmp_path):
    environment = Environment(
        "TestOS", "1", "x86_64", "CPU", "3.13.2", "abc", "cpu", "chromium",
        None, "Chromium", "browser", "none", "playwright", 0,
    )
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
```

- [ ] **Step 2: Run the ingestion test and verify RED**

Run: `uv run --frozen pytest tests/profiling/test_playwright.py -q`

Expected: collection fails because `profiling.playwright` does not exist.

- [ ] **Step 3: Implement strict JSONL ingestion**

Reject malformed JSON, missing/non-numeric durations, or non-scalar metrics with a line-numbered `ValueError`. Map legacy rows to `workload_id=f"browser.{story}"`, `fixture_id="playwright-existing"`, and `actual_backend="chromium"`. Preserve `pfm` and `shapes` as scalar metrics.

Implement `run_playwright()` in `frontend/` with `subprocess.run(["npm", "run", "e2e" if full else "perf:e2e"], cwd=frontend_dir, env=env, text=True, check=False)`. Use the full command so every existing performance story can emit a row; use `npm run perf:e2e` for the targeted quick set. Set `PLOTTER_PERF_FILE` to the requested artifact path, delete an existing file before launch, and raise `RuntimeError` on non-zero exit or a missing result file.

- [ ] **Step 4: Enrich the TypeScript fixture without breaking existing callers**

```typescript
export type PerfRecord = {
  story: string;
  duration_ms: number;
  pfm?: string;
  shapes?: number;
  workload?: string;
  fixture?: string;
  backend?: string;
  metrics?: Record<string, string | number | boolean>;
};
```

Allow `PLOTTER_PERF_FILE` to override the JSONL destination so the Python runner can direct browser records into its artifact directory.

- [ ] **Step 5: Add boot and large-viewport browser timings**

```typescript
import { readFileSync } from "fs";
import { join } from "path";
import { test, expect, ASSETS, freshProject, gotoApp } from "./fixtures";


test("performance: application boot", async ({ page, request, baseURL, recordPerf }) => {
  await freshProject(request, baseURL!, "Perf browser boot");
  const started = Date.now();
  await gotoApp(page);
  recordPerf({
    story: "BROWSER",
    workload: "browser.boot",
    fixture: "empty-project-v1",
    backend: "chromium",
    duration_ms: Date.now() - started,
  });
});


test("performance: large SVG viewport render", async ({ page, request, baseURL, recordPerf }) => {
  await freshProject(request, baseURL!, "Perf large viewport");
  await request.post(`${baseURL}/api/image`, {
    multipart: {
      file: { name: "sample.png", mimeType: "image/png",
              buffer: readFileSync(join(ASSETS, "sample.png")) },
    },
  });
  const added = await (await request.post(`${baseURL}/api/composition/add-layer`, { data: {} })).json();
  const layerId: string = added.composition.layers.at(-1).id;
  const generated = await request.post(
    `${baseURL}/api/composition/layers/${layerId}/pathfinding/generate`,
    { data: { pfm_id: "voronoi_stippling", params: { point_density: 800 } } },
  );
  expect(generated.ok()).toBeTruthy();
  const body = await generated.json();
  const layer = body.composition.layers.find((item: { id: string }) => item.id === layerId);
  const shapes = (String(layer.svg).match(/<(circle|path|line|polyline|polygon|rect)\b/g) || []).length;
  expect(shapes).toBeGreaterThan(0);

  const started = Date.now();
  await gotoApp(page);
  const image = page.locator(".layer-paths").first();
  await expect(image).toBeVisible();
  await image.evaluate((element: HTMLImageElement) => element.decode());
  recordPerf({
    story: "BROWSER",
    workload: "browser.large_viewport",
    fixture: "voronoi-800-v1",
    backend: "chromium",
    duration_ms: Date.now() - started,
    shapes,
    metrics: { shapes },
  });
});
```

These tests assert correctness but contain no duration budget.

- [ ] **Step 6: Run focused Python and Playwright tests**

Run: `uv run --frozen pytest tests/profiling/test_playwright.py -q`

Expected: all ingestion tests pass.

Run: `cd frontend && E2E_SKIP_BUILD=1 npm run e2e -- e2e/perf-browser.spec.ts`

Expected: both browser performance stories pass against the isolated fake-serial backend.

- [ ] **Step 7: Commit browser integration**

```bash
git add profiling/playwright.py tests/profiling/test_playwright.py frontend/e2e/fixtures.ts frontend/e2e/perf-browser.spec.ts
git commit -m "feat: ingest browser performance profiles"
```

---

### Task 8: Native-circle SVG parsing fast path

**Files:**
- Modify: `web/server.py:736-753`
- Create: `tests/test_svg_circle_fastpath.py`

**Interfaces:**
- Consumes: resolved `svgelements.Circle`/`Ellipse` center and radii.
- Preserves: `_circle_meta(element, se, px_to_mm) -> tuple[float, float, float] | None`.
- Falls back to the current `bbox()` logic whenever resolved geometry is absent, non-finite, degenerate, or non-circular.

- [ ] **Step 1: Write failing structural and fidelity tests**

```python
import io
import math
from unittest.mock import patch

import pytest
import svgelements as se

from web import server


def svg(body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">{body}</svg>').encode()


def settings():
    return {**server.DEFAULTS, "reordering": "none"}


def test_resolved_native_circle_does_not_call_expensive_bbox():
    payload = svg('<g transform="translate(10 20) scale(2)"><circle cx="3" cy="4" r="5"/></g>')
    with patch.object(se.Circle, "bbox", side_effect=AssertionError("bbox called")):
        paths = server.svg_to_polylines(payload, settings(), respect_stop=False)
    assert len(paths) == 1
    assert paths[0].arc == pytest.approx({"cx": 16 * 25.4 / 96,
                                          "cy": -28 * 25.4 / 96,
                                          "r": 10 * 25.4 / 96})


def test_ellipse_and_nonuniform_circle_still_flatten():
    for body in ('<ellipse cx="50" cy="50" rx="20" ry="10"/>',
                 '<circle cx="10" cy="10" r="5" transform="scale(2 1)"/>'):
        paths = server.svg_to_polylines(svg(body), settings(), respect_stop=False)
        assert paths
        assert all(getattr(path, "arc", None) is None for path in paths)


def test_circle_fast_path_matches_bbox_geometry_with_numeric_tolerance():
    doc = se.SVG.parse(io.BytesIO(svg('<circle cx="40" cy="30" r="7"/>')))
    circle = next(item for item in doc.elements() if isinstance(item, se.Circle))
    direct = server._circle_meta(circle, se, 25.4 / 96)
    x0, y0, x1, y1 = circle.bbox()
    expected = ((x0 + x1) / 2 * 25.4 / 96,
                -((y0 + y1) / 2) * 25.4 / 96,
                (x1 - x0) / 2 * 25.4 / 96)
    assert direct == pytest.approx(expected, abs=1e-12)
    assert all(math.isfinite(value) for value in direct)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `HOME=/tmp/plotter-circle-test PLOTTER_LOG_FILE=0 uv run --frozen pytest tests/test_svg_circle_fastpath.py -q`

Expected: the structural test fails with `bbox called`.

- [ ] **Step 3: Implement the safe direct-geometry branch**

```python
def _circle_meta(element, se, px_to_mm):
    """Return (cx, cy, r) in machine mm for a circular Circle/Ellipse, else None."""
    if not isinstance(element, (se.Circle, se.Ellipse)):
        return None
    try:
        cx, cy = float(element.cx), float(element.cy)
        rx, ry = float(element.rx), float(element.ry)
        resolved = all(math.isfinite(v) for v in (cx, cy, rx, ry))
    except (AttributeError, TypeError, ValueError):
        resolved = False
    if resolved and rx > 0 and ry > 0 and abs(rx - ry) <= 0.02 * max(rx, ry):
        return cx * px_to_mm, -(cy * px_to_mm), ((rx + ry) / 2) * px_to_mm
    try:
        bb = element.bbox()
    except Exception:
        return None
    if not bb:
        return None
    x0, y0, x1, y1 = bb
    w_, h_ = x1 - x0, y1 - y0
    if w_ <= 0 or h_ <= 0 or abs(w_ - h_) > 0.02 * max(w_, h_):
        return None
    return (x0 + x1) / 2 * px_to_mm, -((y0 + y1) / 2) * px_to_mm, (w_ / 2) * px_to_mm
```

- [ ] **Step 4: Run fidelity, plot-estimate, and profiling workload tests**

Run: `HOME=/tmp/plotter-circle-test PLOTTER_LOG_FILE=0 uv run --frozen pytest tests/test_svg_circle_fastpath.py tests/test_plot_estimate.py tests/test_clip_fidelity.py tests/profiling/test_workloads.py -q`

Expected: all focused tests pass.

- [ ] **Step 5: Run the dense workload in diagnose mode and record evidence**

Run: `uv run --frozen python tools/profile_suite.py diagnose pipeline.svg_dense_circles --backend cpu`

Expected: 8,000 paths, successful checksum validation, `results.json`, `summary.md`, and a `.prof` artifact. Do not add a wall-time assertion.

- [ ] **Step 6: Commit the measured optimization**

```bash
git add web/server.py tests/test_svg_circle_fastpath.py
git commit -m "perf: avoid circle bounding-box parsing"
```

---

### Task 9: CLI, documentation, and artifact hygiene

**Files:**
- Create: `profiling/cli.py`
- Create: `tools/profile_suite.py`
- Create: `tests/profiling/test_cli.py`
- Create: `docs/profiling.md`
- Modify: `.gitignore`
- Modify: `README.md:172-185`
- Modify: `FEATURES.md`

**Interfaces:**
- Produces: `profiling.cli.main(argv: list[str] | None = None) -> int`.
- Commands: `quick`, `full`, `diagnose WORKLOAD_ID`, and `baseline update --from RESULTS --name NAME`.
- Common flags: `--backend`, `--repeat`, `--category`, `--exclude-category`, `--output`, `--baseline`, and `--playwright`.
- A missing baseline file is reported as incomparable and does not fail; a malformed baseline file is an infrastructure error.

- [ ] **Step 1: Write failing CLI contract tests**

```python
import json

from profiling.model import Environment, RunResult, Sample
from profiling.cli import main


def write_error_results(tmp_path):
    environment = Environment(
        "TestOS", "1", "x86_64", "CPU", "3.13.2", "abc", "cpu", "numpy",
        None, "CPU", "numpy", "none", "one", 0,
    )
    sample = Sample(
        "test.error", 1, "fixture", "sha256:fixture", "test", environment,
        "timing", "warm", 0, 0.0, None, {}, {}, "sha256:none", "error",
        "ValueError: broken", {},
    )
    path = tmp_path / "results.json"
    path.write_text(json.dumps(RunResult.new("quick", "abc", [sample]).to_dict()))
    return path


def test_quick_writes_json_and_markdown(tmp_path):
    code = main(["quick", "--backend", "cpu", "--repeat", "1",
                 "--category", "primitive", "--output", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "results.json").is_file()
    assert (tmp_path / "summary.md").is_file()


def test_unknown_diagnose_workload_is_an_infrastructure_error(capsys):
    code = main(["diagnose", "missing.workload"])
    assert code == 2
    assert "Unknown workload" in capsys.readouterr().err


def test_baseline_update_requires_successful_results(tmp_path):
    results = write_error_results(tmp_path)
    code = main(["baseline", "update", "--from", str(results),
                 "--name", "cpu-ci", "--output", str(tmp_path / "baselines")])
    assert code == 1
    assert not (tmp_path / "baselines" / "cpu-ci.json").exists()


def test_missing_baseline_is_treated_as_incomparable(tmp_path):
    code = main(["quick", "--backend", "cpu", "--repeat", "1",
                 "--category", "primitive", "--output", str(tmp_path / "out"),
                 "--baseline", str(tmp_path / "missing.json")])
    assert code == 0
    assert "incomparable" in (tmp_path / "out" / "summary.md").read_text().lower()
```

- [ ] **Step 2: Run CLI tests and verify RED**

Run: `uv run --frozen pytest tests/profiling/test_cli.py -q`

Expected: collection fails because `profiling.cli` does not exist.

- [ ] **Step 3: Implement command dispatch and truthful exit codes**

`quick` selects `workload.quick`; `full` selects every workload in selected categories and defaults to backend `all`; `diagnose` selects exactly one workload and enables diagnostics. `--playwright PATH` ingests pre-existing rows into the same `RunResult`. When `full` includes the browser category and no `--playwright` path is supplied, call `run_playwright(playwright_output_path, full=True)` automatically; missing prerequisites or a browser failure is an infrastructure error. Only `--exclude-category browser` may omit it. A run returns `1` if any sample outcome is `error`, otherwise `0`, regardless of performance warnings. Argument/unknown-workload failures return `2`.

`tools/profile_suite.py` contains only:

```python
from profiling.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Ignore artifacts and document exact commands**

Add `artifacts/profiling/` and `frontend/e2e/perf/results.jsonl` to `.gitignore`. `docs/profiling.md` must document:

```bash
uv run --frozen python tools/profile_suite.py quick
uv run --frozen python tools/profile_suite.py full
uv run --frozen python tools/profile_suite.py full --backend gpu
uv run --frozen python tools/profile_suite.py diagnose pipeline.svg_dense_circles
uv run --frozen python tools/profile_suite.py baseline update --from artifacts/profiling/RUN/results.json --name cpu-ci
```

Explain CPU `.prof`, CUDA trace, MPS Instruments signposts, Python versus GPU memory, warning-only regression policy, explicit browser exclusion, and baseline segmentation. Add the profiler to README's project layout and one engineering feature line to `FEATURES.md`.

- [ ] **Step 5: Run CLI tests and a real quick profile**

Run: `uv run --frozen pytest tests/profiling/test_cli.py -q`

Expected: all CLI tests pass.

Run: `uv run --frozen python tools/profile_suite.py quick --backend cpu --repeat 1 --output /tmp/plotter-profile-quick`

Expected: exit 0 with JSON and Markdown outputs; `git status --short` shows no generated profiling artifacts.

- [ ] **Step 6: Commit CLI and docs**

```bash
git add profiling/cli.py tools/profile_suite.py tests/profiling/test_cli.py docs/profiling.md .gitignore README.md FEATURES.md
git commit -m "feat: add profiling command and guide"
```

---

### Task 10: CI artifact workflow, baseline bootstrap, and final verification

**Files:**
- Create: `.github/workflows/profile.yml`
- Create after a matching run: `profiling/baselines/cpu-ci.json`
- Modify: `frontend/package.json`
- Modify: `docs/profiling.md`

**Interfaces:**
- CI runs the quick CPU profile with five samples and targeted browser performance stories.
- CI uploads `artifacts/profiling/ci/` with 30-day retention.
- CI writes Markdown to `$GITHUB_STEP_SUMMARY`; performance warnings do not fail the job.
- The first CI run bootstraps an artifact; a human explicitly promotes that matching artifact to `cpu-ci.json` in a later commit.

- [ ] **Step 1: Add package scripts used by CI and developers**

Add this script without removing existing ones:

```json
"perf:e2e": "playwright test e2e/perf-pfm.spec.ts e2e/perf-browser.spec.ts"
```

- [ ] **Step 2: Create the warning-only workflow**

```yaml
name: Performance profile

on:
  pull_request:
  workflow_dispatch:

jobs:
  cpu-profile:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - run: uv sync --frozen --group dev
      - run: npm ci
        working-directory: frontend
      - run: npx playwright install --with-deps chromium
        working-directory: frontend
      - name: Browser performance
        run: npm run perf:e2e
        working-directory: frontend
        env:
          PLOTTER_PERF_FILE: ../artifacts/profiling/ci/playwright-results.jsonl
      - name: CPU and browser profile
        run: >-
          uv run --frozen python tools/profile_suite.py quick --backend cpu --repeat 5
          --output artifacts/profiling/ci
          --playwright artifacts/profiling/ci/playwright-results.jsonl
          --baseline profiling/baselines/cpu-ci.json
      - name: Publish summary
        if: always()
        run: cat artifacts/profiling/ci/summary.md >> "$GITHUB_STEP_SUMMARY"
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: performance-profile
          path: artifacts/profiling/ci
          retention-days: 30
```

Ensure CLI arguments used above are implemented and tested in Task 9. The single reporting run must contain both Python and Playwright samples.

- [ ] **Step 3: Document baseline bootstrap without fabricating cross-machine data**

The workflow may start with no matching `cpu-ci` segment. In that case it reports `incomparable` and uploads results. After the first successful run on `ubuntu-latest`, download its `results.json` and execute the explicit baseline command against that file; never commit a macOS measurement under the Linux CI segment. Add this exact promotion process to `docs/profiling.md`.

- [ ] **Step 4: Run all automated verification fresh**

Run: `uv run --frozen pytest -q`

Expected: all Python tests pass with conditional GPU tests either passing on real hardware or explicitly skipped.

Run: `cd frontend && npm run check`

Expected: Svelte/TypeScript check exits 0.

Run: `cd frontend && npm run build`

Expected: production frontend build exits 0.

Run: `uv run --frozen python tools/profile_suite.py quick --backend cpu --repeat 3 --output /tmp/plotter-profile-final`

Expected: quick CPU suite exits 0, all invariants pass, and summary includes median/p90.

Run: `uv run --frozen python tools/profile_suite.py full --backend cpu --repeat 1 --exclude-category browser --output /tmp/plotter-profile-full-cpu`

Expected: full CPU discovery executes every registered PFM and generator exactly once and exits 0 without an implicit skip.

Run: `uv run --frozen python tools/profile_suite.py diagnose pipeline.svg_dense_circles --backend cpu --output /tmp/plotter-profile-circle`

Expected: diagnose exits 0 with `.prof`, memory, JSON, Markdown, and 8,000-path evidence.

Run when `engine.accel.backend_name()` reports MPS or CUDA: `uv run --frozen python tools/profile_suite.py diagnose primitive.assign_nearest_large --backend gpu --output /tmp/plotter-profile-gpu`

Expected: actual backend is `torch-mps` or `torch-cuda`, synchronized samples are present, and GPU fallback is absent.

Run on the same accelerator: `uv run --frozen python tools/profile_suite.py full --backend gpu --repeat 1 --category primitive --category creative --exclude-category browser --output /tmp/plotter-profile-full-gpu`

Expected: every GPU-capable primitive/PFM dispatches a proven accelerator call, unsupported CPU-only creative workloads are not mislabeled as GPU, and the run exits 0.

- [ ] **Step 5: Review generated reports and repository state**

Confirm `summary.md` labels CPU/GPU segments separately, shows browser rows after ingestion, does not turn warnings into failures, and lists any missing baseline as incomparable. Run `git diff --check` and `git status --short`; only intentional source/docs/workflow/baseline changes may remain.

- [ ] **Step 6: Commit CI integration and matching baseline separately**

```bash
git add .github/workflows/profile.yml frontend/package.json docs/profiling.md
git commit -m "ci: publish performance profiles"
```

After a successful matching GitHub run and explicit promotion:

```bash
git add profiling/baselines/cpu-ci.json
git commit -m "perf: establish CPU CI baseline"
```

Do not create the second commit from local macOS/MPS data.

---

## Requirement Coverage

- Full local/CI suite: Tasks 3, 6, 7, 9, and 10.
- CPU timing/profile/memory: Tasks 3 and 5.
- MPS/CUDA synchronization, tracing, memory, and fallback detection: Task 4.
- Every PFM/generator and pipeline coverage: Task 6.
- Browser ingestion and render journeys: Task 7.
- Median/p90, environment segmentation, baselines, and warning-only policy: Tasks 1 and 5.
- CI summary and artifacts: Task 10.
- Measured circle optimization and fidelity protection: Task 8.
- Documentation and honest limitations: Tasks 9 and 10.
