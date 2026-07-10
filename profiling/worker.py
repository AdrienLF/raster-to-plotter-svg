from __future__ import annotations

import cProfile
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from time import perf_counter_ns
import tracemalloc

from .gpu import backend_session
from .model import Environment, Sample
from .workload import Workload, WorkloadCase, WorkloadOutput


@dataclass(frozen=True)
class WorkerRequest:
    workload_id: str
    requested_backend: str
    warmups: int
    repeats: int
    diagnostics: bool
    sample_kind: str = "warm"

    def to_dict(self) -> dict:
        return {
            "workload_id": self.workload_id,
            "requested_backend": self.requested_backend,
            "warmups": self.warmups,
            "repeats": self.repeats,
            "diagnostics": self.diagnostics,
            "sample_kind": self.sample_kind,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkerRequest":
        return cls(
            workload_id=data["workload_id"],
            requested_backend=data["requested_backend"],
            warmups=int(data["warmups"]),
            repeats=int(data["repeats"]),
            diagnostics=bool(data["diagnostics"]),
            sample_kind=data.get("sample_kind", "warm"),
        )


def _sample(workload: Workload, case: WorkloadCase, environment: Environment,
            phase: str, sample_kind: str, index: int, duration_ms: float,
            output: WorkloadOutput, python_peak_bytes: int | None,
            gpu_metrics: dict, artifacts: dict) -> Sample:
    return Sample(
        workload_id=workload.id,
        workload_version=workload.version,
        fixture_id=workload.fixture_id,
        fixture_checksum=case.fixture_checksum,
        category=workload.category,
        environment=environment,
        phase=phase,
        sample_kind=sample_kind,
        sample_index=index,
        duration_ms=duration_ms,
        python_peak_bytes=python_peak_bytes,
        gpu_metrics=dict(gpu_metrics),
        metrics=dict(output.metrics),
        checksum=output.checksum,
        outcome="success",
        reason=None,
        artifacts=dict(artifacts),
    )


def _error_sample(workload: Workload, case: WorkloadCase | None,
                  environment: Environment, phase: str, index: int,
                  exc: BaseException, sample_kind: str = "warm") -> Sample:
    return Sample(
        workload_id=workload.id,
        workload_version=workload.version,
        fixture_id=workload.fixture_id,
        fixture_checksum=case.fixture_checksum if case is not None else "",
        category=workload.category,
        environment=environment,
        phase=phase,
        sample_kind=sample_kind,
        sample_index=index,
        duration_ms=0.0,
        python_peak_bytes=None,
        gpu_metrics={},
        metrics={},
        checksum="",
        outcome="error",
        reason=f"{type(exc).__name__}: {exc}",
        artifacts={},
    )


def _time_once(workload: Workload, case: WorkloadCase, session,
               requires_gpu: bool) -> tuple[WorkloadOutput, float]:
    """Time one run with the GPU queue drained on both sides of the clock."""
    session.reset_usage()
    session.synchronize()
    start = perf_counter_ns()
    output = workload.run(case)
    session.synchronize()
    duration_ms = (perf_counter_ns() - start) / 1_000_000
    if requires_gpu:
        session.assert_gpu_used()
    workload.validate(output)
    return output, duration_ms


def execute_workload(workload: Workload, environment: Environment, warmups: int,
                     repeats: int, diagnostics: bool, artifact_dir: Path,
                     requested_backend: str = "cpu",
                     sample_kind: str = "warm") -> list[Sample]:
    with backend_session(requested_backend) as session:
        return _measure(workload, environment, warmups, repeats, diagnostics,
                        Path(artifact_dir), requested_backend, sample_kind, session)


def _measure(workload: Workload, environment: Environment, warmups: int,
             repeats: int, diagnostics: bool, artifact_dir: Path,
             requested_backend: str, sample_kind: str, session) -> list[Sample]:
    requires_gpu = requested_backend == "gpu"
    try:
        case = workload.prepare()
    except Exception as exc:
        return [_error_sample(workload, None, environment, "prepare", 0, exc, sample_kind)]

    try:
        for _ in range(warmups):
            output = workload.run(case)
            workload.validate(output)
    except Exception as exc:
        return [_error_sample(workload, case, environment, "warmup", 0, exc, sample_kind)]

    samples: list[Sample] = []
    for index in range(repeats):
        try:
            output, duration_ms = _time_once(workload, case, session, requires_gpu)
            samples.append(_sample(workload, case, environment, "timing", sample_kind,
                                   index, duration_ms, output, None, {}, {}))
        except Exception as exc:
            samples.append(_error_sample(workload, case, environment, "timing", index,
                                         exc, sample_kind))
            break

    if diagnostics and not any(item.outcome == "error" for item in samples):
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            profile_path = artifact_dir / f"{workload.id}.prof"
            trace_path = artifact_dir / f"{workload.id}.trace.json"

            profiler = cProfile.Profile()
            session.synchronize()
            with session.diagnostic_trace(trace_path):
                output = profiler.runcall(workload.run, case)
                session.synchronize()
            workload.validate(output)
            profiler.dump_stats(profile_path)

            session.reset_memory()
            tracemalloc.start()
            session.synchronize()
            start = perf_counter_ns()
            output = workload.run(case)
            session.synchronize()
            duration_ms = (perf_counter_ns() - start) / 1_000_000
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            workload.validate(output)
            samples.append(_sample(workload, case, environment, "memory", sample_kind, 0,
                                   duration_ms, output, peak, session.memory_snapshot(),
                                   {"cpu_profile": str(profile_path)}))
        except Exception as exc:
            if tracemalloc.is_tracing():
                tracemalloc.stop()
            samples.append(_error_sample(workload, case, environment, "memory", 0,
                                         exc, sample_kind))

    return samples


def execute_request(request: WorkerRequest, artifact_dir: Path) -> list[Sample]:
    """Resolve a request against the registry and measure it in this process."""
    from .environment import collect_environment
    from .workload import get_workload

    workload = get_workload(request.workload_id)
    with backend_session(request.requested_backend) as session:
        environment = collect_environment(
            request.requested_backend, session.actual_backend,
            workload.metadata, session.metadata(),
        )
        return _measure(workload, environment, request.warmups, request.repeats,
                        request.diagnostics, Path(artifact_dir),
                        request.requested_backend, request.sample_kind, session)


def _write_atomic(path: Path, payload: str) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("usage: python -m profiling.worker REQUEST_JSON RESPONSE_JSON",
              file=sys.stderr)
        return 2

    request_path, response_path = Path(argv[0]), Path(argv[1])
    request = WorkerRequest.from_dict(json.loads(request_path.read_text(encoding="utf-8")))

    from .workloads import register_all

    register_all()
    samples = execute_request(request, response_path.parent)
    payload = json.dumps([_sample_to_dict(item) for item in samples])
    _write_atomic(response_path, payload)
    return 0


def _sample_to_dict(sample: Sample) -> dict:
    from dataclasses import asdict

    return asdict(sample)


if __name__ == "__main__":
    raise SystemExit(main())
