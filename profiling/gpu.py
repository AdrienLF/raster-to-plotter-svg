from __future__ import annotations

from contextlib import contextmanager, nullcontext
import json
import logging
import platform
import subprocess

_GPU_PRIMITIVES = ("_assign_nearest_torch", "_greedy_order_torch")
_FALLBACK_LOGGER = "plotter.engine.accel"
_FALLBACK_EVENT = "accel.gpu_fallback"


class BackendUnavailable(RuntimeError):
    """A requested accelerator is missing, or a GPU run silently fell back."""


class _FallbackCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.events: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage() == _FALLBACK_EVENT:
            self.events.append(record.getMessage())


def _sysctl(key: str) -> str | None:
    try:
        result = subprocess.run(["sysctl", "-n", key], text=True,
                                capture_output=True, check=False)
    except OSError:
        return None
    value = result.stdout.strip()
    return value or None


def accelerator_available() -> bool:
    try:
        import engine.accel as accel
    except Exception:
        return False
    return accel.DEVICE is not None


class BackendSession:
    def __init__(self, kind: str, actual_backend: str, accel_module, torch_module):
        self.kind = kind
        self.actual_backend = actual_backend
        self.accel = accel_module
        self.torch = torch_module
        self._calls = 0
        self._capture = _FallbackCapture()

    # -- dispatch accounting -------------------------------------------------

    def _note_call(self) -> None:
        self._calls += 1

    def reset_usage(self) -> None:
        self._calls = 0
        self._capture.events.clear()

    def assert_gpu_used(self) -> None:
        if self._capture.events:
            raise BackendUnavailable(
                "GPU workload fell back to NumPy (accel.gpu_fallback emitted)")
        if self._calls == 0:
            raise BackendUnavailable("GPU workload used no GPU primitive")

    # -- synchronization and memory -----------------------------------------

    def synchronize(self) -> None:
        if self.torch is None:
            return
        if self.kind == "cuda":
            self.torch.cuda.synchronize()
        elif self.kind == "mps":
            self.torch.mps.synchronize()

    def reset_memory(self) -> None:
        if self.torch is None:
            return
        if self.kind == "cuda":
            self.torch.cuda.reset_peak_memory_stats()

    def memory_snapshot(self) -> dict[str, int]:
        self.synchronize()
        if self.torch is None:
            return {}
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

    # -- identity ------------------------------------------------------------

    def metadata(self) -> dict:
        meta: dict = {"runtime": self.kind, "device": "CPU"}
        if self.torch is not None:
            meta["torch_version"] = str(self.torch.__version__)
        if self.kind == "cuda" and self.torch is not None:
            meta["device"] = str(self.torch.cuda.get_device_name())
            major, minor = self.torch.cuda.get_device_capability()
            meta["compute_capability"] = f"{major}.{minor}"
            meta["cuda_version"] = str(self.torch.version.cuda)
        elif self.kind == "mps":
            meta["device"] = (_sysctl("machdep.cpu.brand_string")
                              or platform.machine())
            meta["hw_model"] = _sysctl("hw.model") or platform.machine()
            meta["macos_version"] = platform.mac_ver()[0] or platform.release()
        return meta

    # -- diagnostics ---------------------------------------------------------

    def diagnostic_trace(self, path):
        if self.torch is None or self.kind == "cpu":
            return nullcontext()
        if self.kind == "cuda":
            return _cuda_trace(self.torch, path)
        return _mps_trace(self.torch, path)


@contextmanager
def _cuda_trace(torch, path):
    activities = [torch.profiler.ProfilerActivity.CPU,
                  torch.profiler.ProfilerActivity.CUDA]
    with torch.profiler.profile(activities=activities) as prof:
        yield
    prof.export_chrome_trace(str(path))


@contextmanager
def _mps_trace(torch, path):
    # torch.mps has no kernel trace export; record that signposts need Instruments.
    with torch.mps.profiler.profile():
        yield
    payload = {
        "backend": "mps",
        "note": "MPS emits os_signpost intervals; capture them with Instruments "
                "(Metal System Trace). No Chrome trace is produced.",
    }
    from pathlib import Path

    Path(path).with_suffix(".mps.json").write_text(json.dumps(payload, indent=2),
                                                   encoding="utf-8")


def _install_usage_wrappers(session, accel_module) -> dict:
    originals = {}
    for name in _GPU_PRIMITIVES:
        original = getattr(accel_module, name, None)
        if original is None:
            continue
        originals[name] = original

        def wrapper(*args, _original=original, **kwargs):
            session._note_call()
            return _original(*args, **kwargs)

        setattr(accel_module, name, wrapper)
    return originals


@contextmanager
def backend_session(requested_backend: str, accel_module=None, torch_module=None):
    """Force a backend for the duration of a measurement.

    `cpu` forces NumPy, `gpu` demands a real MPS/CUDA device, `auto` keeps
    whatever production selected. The accel module's DEVICE and any installed
    wrappers are always restored on exit.
    """
    if accel_module is None:
        import engine.accel as accel_module
    if torch_module is None and requested_backend != "cpu":
        try:
            import torch as torch_module
        except ImportError:
            torch_module = None

    device = getattr(accel_module, "DEVICE", None)

    if requested_backend == "gpu" and device is None:
        raise BackendUnavailable(
            "GPU requested but no MPS/CUDA device is available")

    if requested_backend == "cpu":
        kind = "cpu"
        torch_module = None
    else:
        kind = device.type if device is not None else "cpu"

    original_device = device
    if requested_backend == "cpu":
        accel_module.DEVICE = None

    session = BackendSession(kind, accel_module.backend_name(),
                             accel_module, torch_module)
    originals = _install_usage_wrappers(session, accel_module)

    logger = logging.getLogger(_FALLBACK_LOGGER)
    logger.addHandler(session._capture)
    try:
        session.reset_memory()
        yield session
    finally:
        logger.removeHandler(session._capture)
        for name, original in originals.items():
            setattr(accel_module, name, original)
        accel_module.DEVICE = original_device
