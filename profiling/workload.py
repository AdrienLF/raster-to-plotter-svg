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
