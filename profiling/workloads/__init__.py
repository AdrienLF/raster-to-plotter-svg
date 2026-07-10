"""Idempotent registration of every profiling workload."""
from __future__ import annotations

from ..workload import iter_workloads

_REGISTERED = False


def register_all() -> None:
    """Register primitive, pipeline, and creative workloads exactly once.

    Idempotent within a process, and safe after ``reset_registry_for_tests()``
    clears the registry (the guard is re-armed when the registry is empty).
    """
    global _REGISTERED
    if _REGISTERED and iter_workloads():
        return

    from .creative import register_creative
    from .pipeline import register_pipeline
    from .primitives import register_primitives

    register_primitives()
    register_pipeline()
    register_creative()
    _REGISTERED = True
