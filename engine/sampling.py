"""Point samplers.

Each sampler turns a working raster into a set of weighted points
``(positions Nx2, weights N)`` in working-pixel coordinates. These are the
GPU-heavy stages; the nearest-site assignment + weighted-centroid relaxation run
through :mod:`engine.accel`, which uses Torch (MPS/CUDA) when available.

The same point set is consumed by every style (stippling, TSP, triangulation,
...), so three samplers x seven styles yields the whole first wave.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

from . import accel
from .image_ops import apply_brightness_contrast, darkness, luminance


def _density_map(img: Image.Image, brightness: float = 1.0, contrast: float = 1.0,
                 ignore_white: bool = True) -> np.ndarray:
    gray, alpha = luminance(img)
    gray = apply_brightness_contrast(gray, brightness, contrast)
    d = darkness(gray, alpha)
    if ignore_white:
        d = np.where(d < 0.02, 0.0, d)
    return d.astype(np.float32)


def _dark_pixels(d: np.ndarray, stride: int = 1):
    """Return (positions Nx2 float32 [x,y], weights N) for non-zero density."""
    if stride > 1:
        d = d[::stride, ::stride]
        ys, xs = np.nonzero(d)
        xs = xs * stride
        ys = ys * stride
        w = d[ys // stride, xs // stride]
    else:
        ys, xs = np.nonzero(d)
        w = d[ys, xs]
    pts = np.stack([xs, ys], axis=1).astype(np.float32)
    return pts, w.astype(np.float32)


# ── Weighted Voronoi (Secord 2002) ──────────────────────────────────────────────

class WeightedVoronoiSampler:
    @staticmethod
    def run(img: Image.Image, p: dict, seed: int = 0):
        rng = np.random.default_rng(seed)
        d = _density_map(img, ignore_white=p.get("ignore_white", True))
        h, w = d.shape
        area = w * h

        n = int(p.get("point_density", 500) * area / 50000.0)
        limit = int(p.get("point_limit", 0))
        if limit > 0:
            n = min(n, limit)
        n = max(8, n)

        pts, wt = _dark_pixels(d)
        if pts.shape[0] == 0:
            return np.zeros((0, 2), np.float32), np.zeros((0,), np.float32)
        n = min(n, pts.shape[0])

        lum_power = float(p.get("luminance_power", 5))
        dens_power = float(p.get("density_power", 5))

        # initial sites ~ darkness^luminance_power
        prob = np.power(wt, lum_power)
        prob = prob / prob.sum()
        sites = pts[rng.choice(pts.shape[0], size=n, replace=False, p=prob)].astype(np.float32)

        # relaxation sample weights ~ darkness^density_power
        cw = np.power(wt, dens_power)

        accuracy = float(p.get("voronoi_accuracy", 100))
        stride = max(1, int(round((100 - accuracy) / 12)) + 1)
        spts, sw = _dark_pixels(d, stride=stride)
        scw = np.power(sw, dens_power)

        iters = int(p.get("voronoi_iterations", 8))
        for _ in range(max(1, iters)):
            labels = accel.assign_nearest(spts, sites)
            cent, mass = accel.weighted_centroids(spts, scw, labels, n)
            empty = mass <= 1e-9
            if empty.any():
                resample = rng.choice(pts.shape[0], size=int(empty.sum()), p=prob)
                cent[empty] = pts[resample]
            sites = cent.astype(np.float32)

        # final per-site weight = local density at the site
        ix = np.clip(sites[:, 0].astype(int), 0, w - 1)
        iy = np.clip(sites[:, 1].astype(int), 0, h - 1)
        weights = d[iy, ix]
        return sites, weights


# ── Adaptive (even, tone-mapped distribution) ───────────────────────────────────

class AdaptiveSampler:
    @staticmethod
    def run(img: Image.Image, p: dict, seed: int = 0):
        rng = np.random.default_rng(seed)
        # brightness/contrast are applied to the work image in PFM.run now —
        # passing them again here would double-apply.
        d = _density_map(
            img,
            ignore_white=p.get("ignore_white", True),
        )
        h, w = d.shape
        min_r = max(0.5, float(p.get("min_sample_radius", 1.0)))
        max_r = max(min_r + 0.1, float(p.get("max_sample_radius", 6.0)))

        # Local spacing shrinks in dark areas. Thin a min-spacing grid by the
        # square of (min_r / local_spacing) so dark regions keep more points.
        spacing = max_r - (max_r - min_r) * d
        gy, gx = np.mgrid[0:h:min_r, 0:w:min_r]
        gy = gy.ravel().astype(int)
        gx = gx.ravel().astype(int)
        gy = np.clip(gy + rng.integers(0, max(1, int(min_r)), gy.shape), 0, h - 1)
        gx = np.clip(gx + rng.integers(0, max(1, int(min_r)), gx.shape), 0, w - 1)
        local = spacing[gy, gx]
        accept_prob = np.clip((min_r / np.maximum(local, 1e-3)) ** 2, 0.0, 1.0)
        accept = (rng.random(gx.shape) < accept_prob) & (d[gy, gx] > 0.02)
        sites = np.stack([gx[accept], gy[accept]], axis=1).astype(np.float32)
        weights = d[gy[accept], gx[accept]].astype(np.float32)
        return sites, weights


# ── LBG (Linde–Buzo–Gray adaptive split/merge) ──────────────────────────────────

class LBGSampler:
    @staticmethod
    def run(img: Image.Image, p: dict, seed: int = 0):
        rng = np.random.default_rng(seed)
        d = _density_map(img, ignore_white=True)
        h, w = d.shape
        min_r = max(0.5, float(p.get("stipple_radius_min", 1.0)))
        max_r = max(min_r + 0.1, float(p.get("stipple_radius_max", 8.0)))
        density = float(p.get("density", 50)) / 100.0
        threshold = float(p.get("threshold", 0)) / 100.0

        pts, wt = _dark_pixels(d)
        if pts.shape[0] == 0:
            return np.zeros((0, 2), np.float32), np.zeros((0,), np.float32)

        # seed sites on a coarse grid sized by the mean radius
        mean_r = (min_r + max_r) / 2.0
        gy, gx = np.mgrid[mean_r / 2:h:mean_r, mean_r / 2:w:mean_r]
        sites = np.stack([gx.ravel(), gy.ravel()], axis=1).astype(np.float32)

        # target mass per cell: dark cells (high density) should split sooner
        target_hi = float(np.pi * (min_r ** 2) * (0.4 + density))
        target_lo = float(np.pi * (max_r ** 2) * 0.08)

        max_iter = int(p.get("max_iterations", 20))
        for _ in range(max(1, max_iter)):
            if sites.shape[0] == 0:
                break
            labels = accel.assign_nearest(pts, sites)
            cent, mass = accel.weighted_centroids(pts, wt, labels, sites.shape[0])
            keep = mass > target_lo
            survivors = cent[keep]
            survivor_mass = mass[keep]
            # split heavy cells
            heavy = survivor_mass > target_hi
            new_sites = [survivors]
            if heavy.any():
                jitter = rng.normal(0, min_r, size=(int(heavy.sum()), 2)).astype(np.float32)
                new_sites.append(survivors[heavy] + jitter)
            sites = np.clip(np.concatenate(new_sites, axis=0), [0, 0], [w - 1, h - 1]).astype(np.float32)
            if sites.shape[0] == 0:
                break

        if sites.shape[0] == 0:
            return np.zeros((0, 2), np.float32), np.zeros((0,), np.float32)
        ix = np.clip(sites[:, 0].astype(int), 0, w - 1)
        iy = np.clip(sites[:, 1].astype(int), 0, h - 1)
        weights = d[iy, ix]
        if threshold > 0:
            mask = weights >= threshold
            sites, weights = sites[mask], weights[mask]
        return sites, weights


# ── Poisson-disk (Bridson 2007, variable-density) ───────────────────────────────

class PoissonDiskSampler:
    """Dart-throwing blue-noise sampler with a hard minimum-distance guarantee.

    Unlike ``AdaptiveSampler`` (which thins a jittered grid probabilistically,
    so close pairs can still slip through), every accepted point here is
    rejected against a spatial hash of its neighbours, so two dots can never
    overlap — useful for a fixed pen nib where overlap wastes ink/time.
    """

    @staticmethod
    def run(img: Image.Image, p: dict, seed: int = 0):
        rng = np.random.default_rng(seed)
        d = _density_map(img, ignore_white=p.get("ignore_white", True))
        h, w = d.shape

        min_r = max(0.5, float(p.get("min_radius", 2.0)))
        max_r = max(min_r + 0.1, float(p.get("max_radius", 10.0)))
        k = max(1, int(p.get("candidates", 30)))
        limit = int(p.get("point_limit", 0)) or 500_000

        def radius_at(x: float, y: float) -> float:
            ix = min(max(int(x), 0), w - 1)
            iy = min(max(int(y), 0), h - 1)
            return max_r - (max_r - min_r) * float(d[iy, ix])

        pts0, wt0 = _dark_pixels(d)
        if pts0.shape[0] == 0:
            return np.zeros((0, 2), np.float32), np.zeros((0,), np.float32)

        from scipy.spatial import cKDTree

        # Neighbour conflicts are checked with a KD-tree over all *indexed*
        # points, rebuilt periodically, plus a vectorised brute-force check
        # over the small tail accepted since the last rebuild. A tail-per-cell
        # grid keyed to min_r (Bridson's usual choice) would need a search
        # window scaling with max_r/min_r, which blows up for a wide
        # min/max ratio; the KD-tree's cost is insensitive to that ratio.
        samples: list[tuple[float, float]] = []
        radii: list[float] = []
        active: list[int] = []
        tree = None
        tree_n = 0

        def rebuild_tree() -> None:
            nonlocal tree, tree_n
            tree = cKDTree(np.asarray(samples))
            tree_n = len(samples)

        def has_conflict(x: float, y: float, r: float) -> bool:
            reach = r + max_r
            if tree_n:
                cand = tree.query_ball_point((x, y), r=reach)
                if cand:
                    pts = np.asarray([samples[i] for i in cand])
                    rs = np.asarray([radii[i] for i in cand])
                    dist = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
                    if np.any(dist < np.maximum(r, rs)):
                        return True
            if len(samples) > tree_n:
                tail = np.asarray(samples[tree_n:])
                tail_r = np.asarray(radii[tree_n:])
                dist = np.hypot(tail[:, 0] - x, tail[:, 1] - y)
                if np.any(dist < np.maximum(r, tail_r)):
                    return True
            return False

        prob0 = wt0 / wt0.sum()
        sx, sy = pts0[int(rng.choice(pts0.shape[0], p=prob0))]
        sx, sy = float(sx), float(sy)
        samples.append((sx, sy))
        radii.append(radius_at(sx, sy))
        active.append(0)

        while active and len(samples) < limit:
            ai = int(rng.integers(0, len(active)))
            i = active[ai]
            ox, oy = samples[i]
            orr = radii[i]
            placed = False
            for _ in range(k):
                ang = rng.uniform(0, 2 * math.pi)
                rad = rng.uniform(orr, 2 * orr)
                nx_, ny_ = ox + math.cos(ang) * rad, oy + math.sin(ang) * rad
                if not (0 <= nx_ < w and 0 <= ny_ < h):
                    continue
                if d[int(ny_), int(nx_)] <= 0.02:
                    continue
                nr = radius_at(nx_, ny_)
                if not has_conflict(nx_, ny_, nr):
                    idx = len(samples)
                    samples.append((nx_, ny_))
                    radii.append(nr)
                    active.append(idx)
                    placed = True
                    # Amortised: tail scan cost stays bounded by sqrt(n).
                    if len(samples) - tree_n >= max(200, int(math.sqrt(tree_n or 1))):
                        rebuild_tree()
                    break
            if not placed:
                active.pop(ai)

        sites = np.asarray(samples, dtype=np.float32)
        ix = np.clip(sites[:, 0].astype(int), 0, w - 1)
        iy = np.clip(sites[:, 1].astype(int), 0, h - 1)
        weights = d[iy, ix]
        return sites, weights


SAMPLERS = {
    "voronoi": WeightedVoronoiSampler,
    "adaptive": AdaptiveSampler,
    "lbg": LBGSampler,
    "poisson": PoissonDiskSampler,
}
