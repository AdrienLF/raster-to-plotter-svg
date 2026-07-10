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
