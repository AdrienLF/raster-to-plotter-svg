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
