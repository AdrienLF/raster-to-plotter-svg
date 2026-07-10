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
