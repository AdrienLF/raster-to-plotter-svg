"""Accelerated numeric primitives: nearest-site assignment and path ordering.

These are the only workloads registered for GPU, because they are the code that
actually dispatches to ``engine.accel``'s torch path at the chosen fixture size.
"""
from __future__ import annotations

import numpy as np

from ..workload import Workload, WorkloadCase, WorkloadOutput, register, stable_checksum

SEED = 20260710


def _nearest_case() -> WorkloadCase:
    rng = np.random.default_rng(SEED)
    # points * sites must exceed 1_000_000 so engine.accel takes the GPU path.
    points = rng.random((4000, 2), dtype=np.float32)
    sites = rng.random((1000, 2), dtype=np.float32)
    checksum = stable_checksum([points.shape, sites.shape, float(points.sum())])
    return WorkloadCase(value=(points, sites), fixture_checksum=checksum)


def _nearest_run(case: WorkloadCase) -> WorkloadOutput:
    from engine.accel import assign_nearest

    points, sites = case.value
    idx = assign_nearest(points, sites)
    return WorkloadOutput(
        {"points": int(points.shape[0]), "sites": int(sites.shape[0]),
         "assignments": int(idx.shape[0])},
        stable_checksum([int(idx.shape[0]), int(idx.sum())]),
    )


def _nearest_validate(output: WorkloadOutput) -> None:
    if output.metrics["assignments"] != 4000:
        raise ValueError(f"expected 4000 assignments, got {output.metrics['assignments']}")


def _order_case() -> WorkloadCase:
    rng = np.random.default_rng(SEED)
    # 10_000 polylines is engine.accel's greedy-order GPU crossover.
    starts = rng.random((10_000, 2), dtype=np.float32)
    ends = rng.random((10_000, 2), dtype=np.float32)
    checksum = stable_checksum([starts.shape, float(starts.sum()), float(ends.sum())])
    return WorkloadCase(value=(starts, ends), fixture_checksum=checksum)


def _order_run(case: WorkloadCase) -> WorkloadOutput:
    from engine.accel import greedy_nearest_order

    starts, ends = case.value
    order = list(greedy_nearest_order(starts, ends))
    return WorkloadOutput(
        {"paths": int(starts.shape[0]), "ordered": len(order)},
        stable_checksum([len(order), order[0], order[-1]]),
    )


def _order_validate(output: WorkloadOutput) -> None:
    if output.metrics["ordered"] != 10_000:
        raise ValueError(f"expected 10000 ordered, got {output.metrics['ordered']}")


def register_primitives() -> None:
    register(Workload(
        id="primitive.nearest_site_assignment", version=1, category="primitive",
        fixture_id="nearest-4000x1000", quick=True, backends=("cpu", "gpu"),
        warning_floor_ms=1.0,
        metadata={"dtype": "float32", "problem_size": "points=4000,sites=1000",
                  "tile": 1 << 16, "cold_group": ""},
        prepare=_nearest_case, run=_nearest_run, validate=_nearest_validate,
    ))
    register(Workload(
        id="primitive.greedy_path_order", version=1, category="primitive",
        fixture_id="order-10000", quick=False, backends=("cpu", "gpu"),
        warning_floor_ms=2.0,
        metadata={"dtype": "float32", "problem_size": "paths=10000",
                  "tile": 0, "cold_group": ""},
        prepare=_order_case, run=_order_run, validate=_order_validate,
    ))
