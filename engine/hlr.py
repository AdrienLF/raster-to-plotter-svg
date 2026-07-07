"""Stroke-level hidden-line removal.

Layers ordered near -> far: each layer's strokes are clipped against the
accumulated silhouette (buffered union) of all nearer occluding layers'
strokes, then — if the layer itself occludes — its silhouette joins the
accumulator. Silhouettes come from the layer's *clipped* strokes: geometry
hidden behind a nearer occluder cannot occlude anything farther itself.

Requires shapely >= 2 (buffer / union_all / STRtree).
"""

from __future__ import annotations

MIN_PIECE_MM = 0.3      # drop clipped fragments shorter than this
SIMPLIFY_MM = 0.05
DEFAULT_GAP_MM = 0.15   # visual halo so near strokes read as "in front"
FALLBACK_WIDTH_MM = 0.3


def available() -> bool:
    try:
        import shapely  # noqa: F401
        return True
    except ImportError:  # pragma: no cover - shapely is a project dependency
        return False


def occlude_stack(layers: list[dict], gap_mm: float = DEFAULT_GAP_MM) -> list[list[tuple]]:
    """Clip a depth-ordered stack of stroke layers against each other.

    ``layers`` is ordered NEAR -> FAR; each entry is a dict:
      - ``polylines``: list[list[(x, y)]] in a shared coordinate space (mm)
      - ``widths``: parallel list of stroke widths in mm (0/None -> fallback)
      - ``occludes``: whether this layer's strokes hide layers behind it

    Returns, per layer (same order), a list of ``(points, src_index)`` pieces
    where ``src_index`` is the index of the source polyline in that layer —
    callers use it to carry per-polyline attributes through the clipping.
    """
    import shapely
    from shapely import LineString, STRtree

    occ_parts: list = []        # accumulated silhouette polygons
    tree = None
    out: list[list[tuple]] = []
    for layer in layers:
        polylines = layer.get("polylines") or []
        widths = layer.get("widths") or []
        kept: list[tuple] = []
        for src_index, pl in enumerate(polylines):
            if len(pl) < 2:
                continue
            ls = LineString(pl)
            if tree is not None:
                idx = tree.query(ls)            # bbox candidates
                if len(idx):
                    blocker = shapely.union_all([occ_parts[i] for i in idx])
                    ls = ls.difference(blocker)
            for piece in _lines_of(ls):
                if piece.length >= MIN_PIECE_MM:
                    kept.append(([(p[0], p[1]) for p in piece.coords], src_index))
        out.append(kept)
        if layer.get("occludes"):
            bufs = []
            for pts, src_index in kept:
                w = widths[src_index] if src_index < len(widths) else 0.0
                w = float(w) if w else FALLBACK_WIDTH_MM
                bufs.append(LineString(pts).simplify(SIMPLIFY_MM)
                            .buffer(w / 2.0 + gap_mm, quad_segs=4))
            if bufs:
                sil = shapely.union_all(bufs)
                occ_parts.extend(getattr(sil, "geoms", [sil]))
                tree = STRtree(occ_parts)
    return out


def _lines_of(geom) -> list:
    if geom.is_empty:
        return []
    t = geom.geom_type
    if t == "LineString":
        return [geom]
    if t in ("MultiLineString", "GeometryCollection"):
        return [g for g in geom.geoms if g.geom_type == "LineString"]
    return []
