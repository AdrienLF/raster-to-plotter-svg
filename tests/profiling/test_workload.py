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
