"""Styles: weighted point set -> drawable geometry.

Every style is a pure function ``(sites, weights, params, bounds) -> list[Item]``
and is shared across all sampler families, so the Voronoi / LBG / Adaptive PFMs
differ only in how their points are generated.
"""

from __future__ import annotations

import math

import numpy as np

from .geometry import Dot, Geometry, Item


# ── helpers ─────────────────────────────────────────────────────────────────────

def _radius_px(weight: float, size_mm: float) -> float:
    """Map a darkness weight + a size in mm to a working-pixel radius.

    Working pixels are ~1 pen-width in mm (Area.working_resolution), so this
    reads as roughly true millimeters once rendered. The darkest points get
    the full size_mm radius; lighter points shrink down to 30% of it.
    """
    return size_mm * (0.3 + weight * 0.7)


def _hilbert_order(xs: np.ndarray, ys: np.ndarray, order: int = 16) -> np.ndarray:
    """Return an ordering of points along a Hilbert curve (good TSP-ish path)."""
    n = 1 << order
    x0, x1 = xs.min(), xs.max()
    y0, y1 = ys.min(), ys.max()
    sx = (n - 1) / max(1e-6, x1 - x0)
    sy = (n - 1) / max(1e-6, y1 - y0)
    xi = np.clip(((xs - x0) * sx).astype(np.int64), 0, n - 1)
    yi = np.clip(((ys - y0) * sy).astype(np.int64), 0, n - 1)
    d = np.zeros(len(xs), dtype=np.int64)
    s = n // 2
    while s > 0:
        rx = ((xi & s) > 0).astype(np.int64)
        ry = ((yi & s) > 0).astype(np.int64)
        d += s * s * ((3 * rx) ^ ry)
        # rotate
        swap = ry == 0
        flip = swap & (rx == 1)
        xi_f = xi.copy()
        xi[flip] = s - 1 - xi[flip]
        yi[flip] = s - 1 - yi[flip]
        xt = xi[swap].copy()
        xi[swap] = yi[swap]
        yi[swap] = xt
        s //= 2
    return np.argsort(d)


def _two_opt(path: np.ndarray, max_n: int = 800, passes: int = 2) -> np.ndarray:
    """Light 2-opt improvement for small paths only."""
    n = len(path)
    if n > max_n or n < 4:
        return path
    pts = path

    def dist(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    improved = True
    p = 0
    while improved and p < passes:
        improved = False
        p += 1
        for i in range(1, n - 2):
            for j in range(i + 1, n - 1):
                a, b, c, d_ = pts[i - 1], pts[i], pts[j], pts[j + 1]
                if dist(a, b) + dist(c, d_) > dist(a, c) + dist(b, d_) + 1e-9:
                    pts[i:j + 1] = pts[i:j + 1][::-1]
                    improved = True
    return pts


# ── styles ──────────────────────────────────────────────────────────────────────

def stippling(sites, weights, p, bounds) -> list[Item]:
    size = float(p.get("stipple_size", 0.9))
    items = []
    for (x, y), wgt in zip(sites, weights):
        r = max(0.3, _radius_px(float(wgt), size))
        items.append(Item(lum=float(wgt), dot=Dot(float(x), float(y), r)))
    return items


def dashes(sites, weights, p, bounds) -> list[Item]:
    size = float(p.get("stipple_size", 0.9))
    distortion = float(p.get("distortion", 0.0)) / 100.0
    rng = np.random.default_rng(0)
    items = []
    for (x, y), wgt in zip(sites, weights):
        length = max(0.6, _radius_px(float(wgt), size) * 2.0)
        ang = rng.uniform(-math.pi, math.pi) * distortion
        dx, dy = math.cos(ang) * length / 2, math.sin(ang) * length / 2
        g = Geometry([(float(x - dx), float(y - dy)), (float(x + dx), float(y + dy))])
        items.append(Item(lum=float(wgt), path=g))
    return items


_SHAPE_TYPES = ("circle", "square", "star", "triangle", "cross", "lp")


def _shape_points(kind: str, cx: float, cy: float, r: float, rot: float) -> list[tuple[float, float]]:
    def rt(px, py):
        c, s = math.cos(rot), math.sin(rot)
        return (cx + px * c - py * s, cy + px * s + py * c)

    if kind == "circle":
        return [rt(r * math.cos(t), r * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 18)]
    if kind == "square":
        d = r
        return [rt(-d, -d), rt(d, -d), rt(d, d), rt(-d, d), rt(-d, -d)]
    if kind == "triangle":
        return [rt(r * math.cos(a), r * math.sin(a)) for a in
                (-math.pi / 2, -math.pi / 2 + 2 * math.pi / 3, -math.pi / 2 + 4 * math.pi / 3, -math.pi / 2)]
    if kind == "cross":
        t = r * 0.35
        return [rt(-t, -r), rt(t, -r), rt(t, -t), rt(r, -t), rt(r, t), rt(t, t),
                rt(t, r), rt(-t, r), rt(-t, t), rt(-r, t), rt(-r, -t), rt(-t, -t), rt(-t, -r)]
    if kind == "star":
        pts = []
        for i in range(11):
            a = -math.pi / 2 + i * math.pi / 5
            rr = r if i % 2 == 0 else r * 0.42
            pts.append(rt(rr * math.cos(a), rr * math.sin(a)))
        return pts
    # lp: rounded square via superellipse
    pts = []
    for t in np.linspace(0, 2 * math.pi, 20):
        ct, st = math.cos(t), math.sin(t)
        px = r * math.copysign(abs(ct) ** 0.6, ct)
        py = r * math.copysign(abs(st) ** 0.6, st)
        pts.append(rt(px, py))
    return pts


def shapes(sites, weights, p, bounds) -> list[Item]:
    size = float(p.get("fill_size", 100.0))
    kind = str(p.get("shape_type", "circle"))
    align = bool(p.get("align_rotation", False))
    rot_min = math.radians(float(p.get("min_rotation", 0.0)))
    rot_max = math.radians(float(p.get("max_rotation", 0.0)))
    rng = np.random.default_rng(0)
    items = []
    for (x, y), wgt in zip(sites, weights):
        k = rng.choice(_SHAPE_TYPES) if kind == "random" else kind
        r = max(0.4, _radius_px(float(wgt), 1.8) * size / 100.0)
        rot = 0.0 if align else rng.uniform(rot_min, rot_max) if rot_max != rot_min else rot_min
        g = Geometry(_shape_points(k, float(x), float(y), r, rot), closed=True)
        items.append(Item(lum=float(wgt), path=g))
    return items


def triangulation(sites, weights, p, bounds) -> list[Item]:
    from scipy.spatial import Delaunay
    pts = np.asarray(sites, dtype=float)
    w = np.asarray(weights, dtype=float)
    if len(pts) < 3:
        return []
    if bool(p.get("triangulate_corners", False)):
        bw, bh = bounds
        corners = np.array([[0, 0], [bw, 0], [bw, bh], [0, bh]], dtype=float)
        pts = np.vstack([pts, corners])
        w = np.concatenate([w, np.zeros(4)])
    tri = Delaunay(pts)
    seen: set[tuple[int, int]] = set()
    items = []
    for simplex in tri.simplices:
        for a, b in ((simplex[0], simplex[1]), (simplex[1], simplex[2]), (simplex[2], simplex[0])):
            key = (a, b) if a < b else (b, a)
            if key in seen:
                continue
            seen.add(key)
            g = Geometry([tuple(pts[a]), tuple(pts[b])])
            items.append(Item(lum=float((w[a] + w[b]) / 2), path=g))
    return items


def tree(sites, weights, p, bounds) -> list[Item]:
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import minimum_spanning_tree
    from scipy.spatial import cKDTree
    pts = np.asarray(sites, dtype=float)
    w = np.asarray(weights, dtype=float)
    n = len(pts)
    if n < 2:
        return []
    k = min(8, n - 1)
    tree_kd = cKDTree(pts)
    dist, idx = tree_kd.query(pts, k=k + 1)
    rows, cols, vals = [], [], []
    for i in range(n):
        for j in range(1, k + 1):
            rows.append(i)
            cols.append(idx[i, j])
            vals.append(dist[i, j])
    graph = csr_matrix((vals, (rows, cols)), shape=(n, n))
    mst = minimum_spanning_tree(graph).tocoo()
    items = []
    for a, b in zip(mst.row, mst.col):
        g = Geometry([tuple(pts[a]), tuple(pts[b])])
        items.append(Item(lum=float((w[a] + w[b]) / 2), path=g))
    return items


def diagram(sites, weights, p, bounds) -> list[Item]:
    from scipy.spatial import Voronoi
    pts = np.asarray(sites, dtype=float)
    if len(pts) < 4:
        return []
    bw, bh = bounds
    vor = Voronoi(pts)
    items = []
    for (a, b) in vor.ridge_vertices:
        if a < 0 or b < 0:
            continue
        pa = vor.vertices[a]
        pb = vor.vertices[b]
        # keep ridges that intersect the page (cheap reject)
        if (max(pa[0], pb[0]) < 0 or min(pa[0], pb[0]) > bw or
                max(pa[1], pb[1]) < 0 or min(pa[1], pb[1]) > bh):
            continue
        items.append(Item(lum=0.5, path=Geometry([tuple(pa), tuple(pb)])))
    return items


def tsp(sites, weights, p, bounds) -> list[Item]:
    pts = np.asarray(sites, dtype=float)
    n = len(pts)
    if n < 2:
        return []
    order = _hilbert_order(pts[:, 0], pts[:, 1])
    path = pts[order]
    path = _two_opt(path)
    merge = bool(p.get("merge_tsp_paths", True))
    avg = float(np.mean(weights)) if len(weights) else 0.5
    if merge:
        g = Geometry([tuple(pt) for pt in path])
        return [Item(lum=avg, path=g)]
    # split into segments
    items = []
    for a, b in zip(path, path[1:]):
        items.append(Item(lum=avg, path=Geometry([tuple(a), tuple(b)])))
    return items


STYLES = {
    "stippling": stippling,
    "dashes": dashes,
    "shapes": shapes,
    "triangulation": triangulation,
    "tree": tree,
    "diagram": diagram,
    "tsp": tsp,
}
