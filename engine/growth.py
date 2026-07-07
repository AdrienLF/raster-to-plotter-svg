"""Differential growth: self-avoiding polylines that grow and fold.

Closed loops (or open curves) are seeded in dark image areas and grow by edge
subdivision while alignment, node repulsion and a darkness-gradient bias push
the curve into organic brain-coral folds. Emits continuous plottable strokes.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.spatial import cKDTree

from .geometry import Geometry, Item
from .image_ops import darkness, luminance

MAX_NODES = 60_000
MAX_PATHS = 512
DARK_GAIN = 20.0        # np.gradient of a blurred [0,1] map is tiny; amplify


def _blur(arr):
    try:
        import cv2
        return cv2.GaussianBlur(arr, (9, 9), 0)
    except Exception:
        from scipy.ndimage import gaussian_filter
        return gaussian_filter(arr, 2.0)


def _seed_paths(dark, v, rng):
    h, w = dark.shape
    n_seeds = min(MAX_PATHS, int(v["seed_count"]))
    min_sep = 4.0 * float(v["repulsion_radius"])
    r0 = 2.0 * float(v["min_dist"])
    ys, xs = np.nonzero(dark > 0.03)
    if len(xs) == 0:                        # blank image: one centre seed
        xs = np.array([w // 2])
        ys = np.array([h // 2])
    probs = dark[ys, xs] ** float(v["seed_power"])
    total = float(probs.sum())
    probs = probs / total if total > 0 else None
    take = min(len(xs), max(n_seeds * 30, n_seeds))
    order = rng.choice(len(xs), size=take, replace=False, p=probs)
    chosen: list[tuple[float, float]] = []
    for k in order:
        x, y = float(xs[k]), float(ys[k])
        if all((x - cx) ** 2 + (y - cy) ** 2 >= min_sep ** 2 for cx, cy in chosen):
            chosen.append((x, y))
            if len(chosen) >= n_seeds:
                break
    paths, closed = [], []
    make_closed = bool(v["closed_loops"])
    for (cx, cy) in chosen:
        a0 = rng.uniform(0, 2 * math.pi)
        if make_closed:
            pts = [(cx + r0 * math.cos(a0 + i * math.pi / 3),
                    cy + r0 * math.sin(a0 + i * math.pi / 3)) for i in range(6)]
        else:
            pts = [(cx + t * r0 * math.cos(a0), cy + t * r0 * math.sin(a0))
                   for t in (-1.0, 0.0, 1.0)]
        paths.append(np.asarray(pts, dtype=np.float32))
        closed.append(make_closed)
    return paths, closed


def _resample(a, is_closed, dark, min_dist, max_dist, jitter, rng, w, h):
    """Split long edges (sooner in dark areas) and merge collapsed nodes."""
    n = len(a)
    if n < 3:
        return a
    b = np.vstack([a, a[:1]]) if is_closed else a       # edges: b[i] -> b[i+1]
    seg = np.linalg.norm(b[1:] - b[:-1], axis=1)
    mid = (b[1:] + b[:-1]) * 0.5
    ix = np.clip(mid[:, 0].astype(np.int64), 0, w - 1)
    iy = np.clip(mid[:, 1].astype(np.int64), 0, h - 1)
    d_mid = dark[iy, ix]
    # dark areas split sooner (denser folds); threshold in [1.5*min_dist, max_dist]
    thr = np.maximum(max_dist + (1.5 * min_dist - max_dist) * d_mid, 1.5 * min_dist)
    ins = seg > thr
    # Random node injection (darkness-biased) is what drives sustained growth:
    # once alignment and repulsion balance, no edge ever crosses the length
    # threshold and the curve would freeze at its equilibrium shape.
    k = int(rng.integers(0, len(seg)))
    if seg[k] > 0.9 * min_dist and rng.random() < 0.2 + 0.8 * float(d_mid[k]):
        ins = ins.copy()
        ins[k] = True
    if ins.any():
        mids = (mid[ins] + rng.normal(0.0, jitter, size=(int(ins.sum()), 2))
                ).astype(np.float32)
        pos = np.nonzero(ins)[0] + 1        # insert before a[pos]; pos==n appends
        a = np.insert(a, pos, mids, axis=0)
        n = len(a)
    if n > 6:
        b = np.vstack([a, a[:1]]) if is_closed else a
        seg = np.linalg.norm(b[1:] - b[:-1], axis=1)
        short = seg < 0.5 * min_dist
        drop = np.zeros(n, dtype=bool)
        if is_closed:
            drop = short & np.roll(short, 1)    # both incident edges short
        else:
            drop[1:-1] = short[:-1] & short[1:]
        drop[1:] &= ~drop[:-1]              # never drop two in a row
        if is_closed and drop[0] and drop[-1]:
            drop[0] = False
        if drop.any() and (n - int(drop.sum())) >= 4:
            a = a[~drop]
    return a


def grow(paths, closed, dark, v, rng, on_progress=None):
    h, w = dark.shape
    k_align = float(v["k_align"])
    k_rep = float(v["k_rep"])
    k_dark = float(v["k_dark"])
    R = max(1.0, float(v["repulsion_radius"]))
    min_dist = max(0.5, float(v["min_dist"]))
    max_dist = max(min_dist * 1.5, float(v["max_dist"]))
    jitter = float(v["jitter"])
    # The per-node step clamp is the stability guarantee — never remove it.
    max_step = 0.4 * min_dist
    iters = int(v["iterations"])
    gy_, gx_ = np.gradient(_blur(dark))     # np.gradient: axis 0 (y) first
    still = 0
    for it in range(iters):
        lens = [len(a) for a in paths]
        offsets = np.concatenate([[0], np.cumsum(lens)]).astype(np.int64)
        N = int(offsets[-1])
        P = np.concatenate(paths).astype(np.float32)
        pid = np.repeat(np.arange(len(paths)), lens)
        idx = np.arange(N)
        prev, nxt = idx - 1, idx + 1
        for k in range(len(paths)):
            s, e = int(offsets[k]), int(offsets[k + 1])
            if closed[k]:
                prev[s], nxt[e - 1] = e - 1, s
            else:
                prev[s], nxt[e - 1] = s, e - 1
        F = k_align * ((P[prev] + P[nxt]) * 0.5 - P)

        tree = cKDTree(P)
        pairs = tree.query_pairs(R, output_type="ndarray")
        if len(pairs):
            i, j = pairs[:, 0], pairs[:, 1]
            same = pid[i] == pid[j]
            gap = np.abs(i - j)
            plen = np.asarray(lens)[pid[i]]
            # Skip only direct edge partners (their spacing is the alignment
            # spring's job). Repulsion between farther ring-neighbors is what
            # inflates the curve — the engine of differential growth.
            adjacent = same & ((gap <= 1) | (gap >= plen - 1))
            keep = ~adjacent
            i, j = i[keep], j[keep]
            if len(i):
                d = P[i] - P[j]
                dist = np.maximum(np.linalg.norm(d, axis=1), 1e-6)
                f = (k_rep * (1.0 - dist / R) / dist)[:, None] * d
                np.add.at(F, i, f)          # indices repeat: += would drop hits
                np.add.at(F, j, -f)

        ixp = np.clip(P[:, 0].astype(np.int64), 0, w - 1)
        iyp = np.clip(P[:, 1].astype(np.int64), 0, h - 1)
        F[:, 0] += k_dark * DARK_GAIN * gx_[iyp, ixp]
        F[:, 1] += k_dark * DARK_GAIN * gy_[iyp, ixp]

        mag = np.linalg.norm(F, axis=1)
        scale = np.minimum(1.0, max_step / np.maximum(mag, 1e-9))
        P = P + F * scale[:, None]
        np.clip(P[:, 0], 0, w - 1, out=P[:, 0])
        np.clip(P[:, 1], 0, h - 1, out=P[:, 1])

        paths = [P[offsets[k]:offsets[k + 1]] for k in range(len(paths))]
        if N < MAX_NODES:
            paths = [_resample(a, closed[k], dark, min_dist, max_dist,
                               jitter, rng, w, h)
                     for k, a in enumerate(paths)]
        moved = float(np.mean(mag * scale)) if N else 0.0
        still = still + 1 if moved < 0.01 * min_dist else 0
        if still >= 10:
            break
        if on_progress and it % 20 == 0:
            on_progress("growing", 0.1 + 0.7 * it / max(1, iters))
    return paths


def run_growth(work, v, seed, bounds):
    w, h = bounds
    gray, alpha = luminance(work)
    dark = darkness(gray, alpha)
    rng = np.random.default_rng(int(seed))
    paths, closed = _seed_paths(dark, v, rng)
    if not paths:
        return []
    paths = grow(paths, closed, dark, v, rng)
    items = []
    for a, c in zip(paths, closed):
        if len(a) < 3:
            continue
        ix = np.clip(a[:, 0].astype(np.int64), 0, w - 1)
        iy = np.clip(a[:, 1].astype(np.int64), 0, h - 1)
        lum = float(dark[iy, ix].mean())
        items.append(Item(lum=lum,
                          path=Geometry([(float(x), float(y)) for x, y in a],
                                        closed=c)))
    return items
