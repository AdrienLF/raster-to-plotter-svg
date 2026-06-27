"""GPU/CPU backend abstraction.

Exposes two hot primitives used by every sampler:
  * ``assign_nearest(points, sites)``  -> nearest-site index per point
  * ``weighted_centroids(points, weights, labels, n)`` -> per-site centroid + mass

When PyTorch with MPS (Metal) or CUDA is available the nearest-site assignment
runs on the GPU in tiles; otherwise it falls back to ``scipy.spatial.cKDTree``.
Results are identical modulo floating-point summation order.
"""

from __future__ import annotations

import logging

import numpy as np

_log = logging.getLogger("plotter.engine.accel")

try:  # optional GPU dependency
    import torch
    _HAS_TORCH = True
except Exception:  # pragma: no cover - torch optional
    torch = None  # type: ignore
    _HAS_TORCH = False


def _pick_device():
    if not _HAS_TORCH:
        return None
    try:
        if torch.backends.mps.is_available():
            return torch.device("mps")
    except Exception:
        pass
    try:
        if torch.cuda.is_available():
            return torch.device("cuda")
    except Exception:
        pass
    return None  # plain torch-CPU isn't worth it over scipy/numpy


DEVICE = _pick_device()


def backend_name() -> str:
    if DEVICE is not None:
        return f"torch-{DEVICE.type}"
    return "numpy"


def using_gpu() -> bool:
    return DEVICE is not None


def _assign_nearest_torch(points: np.ndarray, sites: np.ndarray, tile: int = 1 << 16) -> np.ndarray:
    pt = torch.as_tensor(points, dtype=torch.float32, device=DEVICE)
    st = torch.as_tensor(sites, dtype=torch.float32, device=DEVICE)
    n = pt.shape[0]
    labels = torch.empty(n, dtype=torch.int64, device=DEVICE)
    for i in range(0, n, tile):
        chunk = pt[i:i + tile]                       # (c, 2)
        d = torch.cdist(chunk, st)                   # (c, M)
        labels[i:i + tile] = torch.argmin(d, dim=1)
    return labels.to("cpu").numpy()


def assign_nearest(points: np.ndarray, sites: np.ndarray) -> np.ndarray:
    """Index of the nearest site for each point. points (N,2), sites (M,2)."""
    points = np.ascontiguousarray(points, dtype=np.float32)
    sites = np.ascontiguousarray(sites, dtype=np.float32)
    if sites.shape[0] == 0:
        return np.zeros(points.shape[0], dtype=np.int64)
    if DEVICE is not None and points.shape[0] * sites.shape[0] > 1_000_000:
        try:
            return _assign_nearest_torch(points, sites)
        except Exception as exc:
            _log.warning("accel.gpu_fallback", extra={"fields": {
                "backend": backend_name(), "err": str(exc)}})
    from scipy.spatial import cKDTree
    _, idx = cKDTree(sites).query(points, k=1)
    return np.asarray(idx, dtype=np.int64)


# Greedy nearest-neighbour ordering crosses over to GPU only above this many
# polylines: the tour is sequential, so below the crossover per-step kernel-launch
# overhead makes numpy (no launch cost) faster than CUDA. Measured ~10k on an
# RTX 3090; numpy is ~7x faster than the old O(n^2) python loop at n=5000.
_GREEDY_GPU_MIN = 10_000


def _greedy_order_numpy(starts: np.ndarray, ends: np.ndarray) -> list[int]:
    n = starts.shape[0]
    visited = np.zeros(n, dtype=bool)
    order = np.empty(n, dtype=np.intp)
    order[0] = 0
    visited[0] = True
    last = ends[0]
    for i in range(1, n):
        d = ((starts - last) ** 2).sum(1)
        d[visited] = np.inf
        cur = int(d.argmin())
        order[i] = cur
        visited[cur] = True
        last = ends[cur]
    return order.tolist()


def _greedy_order_torch(starts: np.ndarray, ends: np.ndarray) -> list[int]:
    st = torch.as_tensor(starts, dtype=torch.float32, device=DEVICE)
    en = torch.as_tensor(ends, dtype=torch.float32, device=DEVICE)
    n = st.shape[0]
    visited = torch.zeros(n, dtype=torch.bool, device=DEVICE)
    order = torch.empty(n, dtype=torch.long, device=DEVICE)
    order[0] = 0
    visited[0] = True
    last = en[0]
    for i in range(1, n):
        d = (st - last).pow(2).sum(1).masked_fill_(visited, float("inf"))
        cur = torch.argmin(d)
        order[i] = cur
        visited[cur] = True
        last = en[cur]
    return order.tolist()


def greedy_nearest_order(starts, ends) -> list[int]:
    """Greedy nearest-neighbour visiting order for pen-path reordering.

    ``starts``/``ends``: (n, 2) — the first/last point of each polyline. Returns
    indices: start at polyline 0, then repeatedly jump to the nearest unvisited
    polyline *start* measured from the current polyline's *end*. Identical tour to
    the naive O(n^2) loop (same tie-breaking), just vectorised; GPU only kicks in
    for very dense drawings where the O(n^2) distance work beats launch overhead.
    """
    starts = np.ascontiguousarray(starts, dtype=np.float32)
    ends = np.ascontiguousarray(ends, dtype=np.float32)
    n = starts.shape[0]
    if n <= 1:
        return list(range(n))
    if DEVICE is not None and n >= _GREEDY_GPU_MIN:
        try:
            return _greedy_order_torch(starts, ends)
        except Exception as exc:
            _log.warning("accel.gpu_fallback", extra={"fields": {
                "op": "greedy_order", "backend": backend_name(), "err": str(exc)}})
    return _greedy_order_numpy(starts, ends)


def weighted_centroids(
    points: np.ndarray,
    weights: np.ndarray,
    labels: np.ndarray,
    n_sites: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Density-weighted centroid and total mass per site.

    Returns (centroids (n_sites,2), mass (n_sites,)). Sites with no assigned
    mass get a zero centroid (caller decides how to respawn them).
    """
    labels = np.asarray(labels, dtype=np.int64)
    w = np.asarray(weights, dtype=np.float64)
    wx = np.bincount(labels, weights=w * points[:, 0], minlength=n_sites)
    wy = np.bincount(labels, weights=w * points[:, 1], minlength=n_sites)
    mass = np.bincount(labels, weights=w, minlength=n_sites)
    cent = np.zeros((n_sites, 2), dtype=np.float64)
    nz = mass > 1e-12
    cent[nz, 0] = wx[nz] / mass[nz]
    cent[nz, 1] = wy[nz] / mass[nz]
    return cent, mass
