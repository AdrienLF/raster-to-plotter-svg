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
