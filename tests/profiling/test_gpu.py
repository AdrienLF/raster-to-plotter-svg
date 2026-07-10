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


@pytest.mark.skipif(
    __import__("engine.accel", fromlist=["DEVICE"]).DEVICE is None,
    reason="no MPS/CUDA accelerator visible",
)
def test_real_accelerator_session_reports_device_and_synchronizes():
    with backend_session("gpu") as session:
        assert session.actual_backend.startswith("torch-")
        session.reset_usage()
        session.synchronize()
        assert isinstance(session.memory_snapshot(), dict)
        assert "device" in session.metadata()
