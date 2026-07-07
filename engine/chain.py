"""Endpoint welding + Euler-trail chaining of polylines.

Turns many short open polylines that share endpoints (Delaunay edges, MST
edges, Voronoi ridges, ...) into few long continuous pen strokes. Two entry
points: exact welds on engine Items (working px, tol=0) and tolerance welds
on plot polylines (machine mm, tol>0).
"""

from __future__ import annotations

import math

from .geometry import Geometry, Item

# Above this many open polylines, chaining is skipped (graph build cost).
MAX_OPEN = 200_000


def _weld_nodes(endpoints: list[tuple[float, float]], tol: float):
    """Cluster endpoint coordinates into node ids.

    Returns (node_of, centroids): node_of[k] is the node id of endpoints[k];
    centroids[node] is the running-mean position of that weld class. With
    tol == 0 endpoints weld only when equal after rounding to 6 decimals
    (lossless for scipy-shared vertices). With tol > 0 a dict grid with cell
    size == tol is searched 3x3 around each endpoint and the endpoint joins
    the nearest existing class whose centroid is within tol. Because we test
    against centroids, chained drift is bounded by ~2*tol.
    """
    node_of: list[int] = []
    centroids: list[tuple[float, float]] = []
    if tol <= 0:
        exact: dict[tuple[float, float], int] = {}
        for (x, y) in endpoints:
            key = (round(x, 6), round(y, 6))
            nid = exact.get(key)
            if nid is None:
                nid = len(centroids)
                exact[key] = nid
                centroids.append((x, y))
            node_of.append(nid)
        return node_of, centroids

    counts: list[int] = []
    grid: dict[tuple[int, int], list[int]] = {}
    for (x, y) in endpoints:
        ci, cj = int(math.floor(x / tol)), int(math.floor(y / tol))
        best = None
        for dj in (-1, 0, 1):
            for di in (-1, 0, 1):
                for nid in grid.get((ci + di, cj + dj), ()):
                    px, py = centroids[nid]
                    d = math.hypot(px - x, py - y)
                    if d <= tol and (best is None or d < best[0]):
                        best = (d, nid)
        if best is None:
            nid = len(centroids)
            centroids.append((x, y))
            counts.append(1)
            grid.setdefault((ci, cj), []).append(nid)
        else:
            nid = best[1]
            c = counts[nid]
            px, py = centroids[nid]
            centroids[nid] = ((px * c + x) / (c + 1), (py * c + y) / (c + 1))
            counts[nid] = c + 1
        node_of.append(nid)
    return node_of, centroids


def _trails(num_edges: int, adj: list[list[tuple[int, int, bool]]],
            degree: list[int]) -> list[list[tuple[int, bool]]]:
    """Euler-trail decomposition of an undirected multigraph.

    adj[node] = list of (edge_id, other_node, reversed). Returns trails as
    lists of (edge_id, reversed) in draw order. Hierholzer stack splicing is
    only valid on graphs whose degrees are all even, so each component's 2k
    odd vertices are first paired with k virtual edges; the component then has
    one Euler circuit, which is split back at the virtual edges into exactly
    k contiguous trails (or kept whole as a circuit when k == 0).
    """
    n = len(adj)

    # Connected components (only nodes that have edges matter).
    comp = [-1] * n
    ncomp = 0
    for s in range(n):
        if comp[s] != -1 or not adj[s]:
            continue
        comp[s] = ncomp
        stack = [s]
        while stack:
            u = stack.pop()
            for (_, v, _) in adj[u]:
                if comp[v] == -1:
                    comp[v] = ncomp
                    stack.append(v)
        ncomp += 1

    # Pair odd-degree vertices within each component via virtual edges.
    odd_by_comp: dict[int, list[int]] = {}
    for u in range(n):
        if degree[u] % 2 == 1:
            odd_by_comp.setdefault(comp[u], []).append(u)
    adj2 = [list(lst) for lst in adj]
    next_eid = num_edges
    virtual: set[int] = set()
    for nodes in odd_by_comp.values():
        for a, b in zip(nodes[0::2], nodes[1::2]):
            adj2[a].append((next_eid, b, False))
            adj2[b].append((next_eid, a, True))
            virtual.add(next_eid)
            next_eid += 1

    used = [False] * next_eid
    cursor = [0] * n

    def walk(start: int) -> list[tuple[int, bool]]:
        stack: list[tuple[int, tuple[int, bool] | None]] = [(start, None)]
        out: list[tuple[int, bool]] = []
        while stack:
            node, arrive = stack[-1]
            nxt = None
            while cursor[node] < len(adj2[node]):
                e, other, rev = adj2[node][cursor[node]]
                cursor[node] += 1
                if not used[e]:
                    nxt = (e, other, rev)
                    break
            if nxt is not None:
                used[nxt[0]] = True
                stack.append((nxt[1], (nxt[0], nxt[2])))
            else:
                stack.pop()
                if arrive is not None:
                    out.append(arrive)
        out.reverse()
        return out

    trails: list[list[tuple[int, bool]]] = []
    for node in range(n):
        circ = walk(node)       # empty when all incident edges are used
        if not circ:
            continue
        vk = next((i for i, (e, _) in enumerate(circ) if e in virtual), None)
        if vk is None:          # pure circuit, no odd vertices in component
            trails.append(circ)
            continue
        # Rotate the circuit so it starts right after a virtual edge (the
        # wrap-around junction is a genuine adjacency), drop that edge, then
        # split the remainder at the other virtual edges.
        rot = circ[vk + 1:] + circ[:vk]
        cur: list[tuple[int, bool]] = []
        for (e, rev) in rot:
            if e in virtual:
                if cur:
                    trails.append(cur)
                    cur = []
            else:
                cur.append((e, rev))
        if cur:
            trails.append(cur)
    return trails


def _chain_point_lists(opens: list[list[tuple[float, float]]], tol: float):
    """Chain open polylines; returns (merged_point_lists, trail_edge_ids)."""
    endpoints: list[tuple[float, float]] = []
    for seg in opens:
        endpoints.append(tuple(seg[0]))
        endpoints.append(tuple(seg[-1]))
    node_of, centroids = _weld_nodes(endpoints, tol)

    adj: list[list[tuple[int, int, bool]]] = [[] for _ in range(len(centroids))]
    degree = [0] * len(centroids)
    for e in range(len(opens)):
        u, v = node_of[2 * e], node_of[2 * e + 1]
        adj[u].append((e, v, False))   # traverse start -> end
        adj[v].append((e, u, True))    # traverse end -> start
        degree[u] += 1
        degree[v] += 1

    merged: list[list[tuple[float, float]]] = []
    trail_edges: list[list[int]] = []
    for trail in _trails(len(opens), adj, degree):
        pts: list[tuple[float, float]] = []
        eids: list[int] = []
        for (e, rev) in trail:
            seg = list(reversed(opens[e])) if rev else list(opens[e])
            if pts and math.hypot(pts[-1][0] - seg[0][0],
                                  pts[-1][1] - seg[0][1]) < 1e-9:
                seg = seg[1:]
            pts.extend(seg)
            eids.append(e)
        if len(pts) >= 2:
            merged.append(pts)
            trail_edges.append(eids)
    return merged, trail_edges


def chain_items(items: list[Item], tol: float = 0.0) -> list[Item]:
    """Engine-level chaining. Dots and closed paths pass through untouched.
    Merged Item.lum is the length-weighted mean of the source items' lums."""
    passthrough: list[Item] = []
    open_items: list[Item] = []
    for it in items:
        if it.path is None or it.path.closed or len(it.path.points) < 2:
            passthrough.append(it)
        else:
            open_items.append(it)
    if len(open_items) < 2 or len(open_items) > MAX_OPEN:
        return items

    opens = [it.path.points for it in open_items]

    def seg_len(pts):
        return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                   for i in range(len(pts) - 1))

    lengths = [max(1e-9, seg_len(pts)) for pts in opens]
    merged, trail_edges = _chain_point_lists(opens, tol)
    out = list(passthrough)
    for pts, eids in zip(merged, trail_edges):
        wsum = sum(lengths[e] for e in eids)
        lum = sum(open_items[e].lum * lengths[e] for e in eids) / wsum
        out.append(Item(lum=float(lum), path=Geometry(pts)))
    return out


def chain_polylines(polylines: list, tol: float) -> list:
    """Plot-level chaining on machine-mm polylines (plain point-lists).
    ArcPath instances (have an .arc attr) and closed polylines pass through."""
    if tol <= 0 or len(polylines) < 2:
        return polylines
    passthrough, opens = [], []
    for poly in polylines:
        if getattr(poly, "arc", None) is not None or len(poly) < 2 or \
                (len(poly) > 2 and poly[0] == poly[-1]):
            passthrough.append(poly)
        else:
            opens.append([tuple(pt) for pt in poly])
    if len(opens) < 2 or len(opens) > MAX_OPEN:
        return polylines
    merged, _ = _chain_point_lists(opens, tol)
    return passthrough + merged
