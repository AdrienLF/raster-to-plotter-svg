"""Vector-state tessellation patterns driven by raster tone.

A pattern is a lattice (vectors a, b) plus 32 ordered tile states; the
renderer picks or interpolates a state per cell from the cell's mean tone.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image

from .geometry import Geometry, Item
from .image_ops import luminance

Point = tuple[float, float]
STATE_COUNT = 32
ALPHA_COVER_MIN = 0.05
MAX_TILES = 40_000


@dataclass(frozen=True)
class TilePath:
    points: tuple[Point, ...]
    closed: bool = False


@dataclass(frozen=True)
class TileState:
    paths: tuple[TilePath, ...]


@dataclass(frozen=True)
class ParameterBinding:
    layer_id: str
    attribute_id: str
    light: float
    dark: float
    curve: tuple[tuple[str, float], ...] | None = None


@dataclass(frozen=True)
class TessellationPattern:
    id: str
    name: str
    source: str
    a: Point
    b: Point
    bounds: tuple[float, float, float, float]
    states: tuple[TileState, ...]
    bindings: tuple[ParameterBinding, ...] = ()

    def __post_init__(self):
        if len(self.states) != STATE_COUNT:
            raise ValueError("Tessellation patterns require exactly 32 states")
        det = self.a[0] * self.b[1] - self.a[1] * self.b[0]
        if not math.isfinite(det) or abs(det) < 1e-9:
            raise ValueError("Tessellation lattice vectors must be finite and non-collinear")


def _compatible(a: TileState, b: TileState) -> bool:
    return len(a.paths) == len(b.paths) and all(
        pa.closed == pb.closed and len(pa.points) == len(pb.points)
        for pa, pb in zip(a.paths, b.paths)
    )


def state_at_tone(pattern: TessellationPattern, tone: float) -> TileState:
    """Tile state for a tone in 0-1: lerp between neighbours when their
    path topology matches, otherwise snap to the nearest whole state."""
    pos = max(0.0, min(1.0, float(tone))) * (STATE_COUNT - 1)
    lo = int(math.floor(pos))
    hi = min(STATE_COUNT - 1, lo + 1)
    f = pos - lo
    a, b = pattern.states[lo], pattern.states[hi]
    if lo == hi or not _compatible(a, b):
        return a if f < 0.5 else b
    return TileState(tuple(
        TilePath(tuple(
            (ax + (bx - ax) * f, ay + (by - ay) * f)
            for (ax, ay), (bx, by) in zip(pa.points, pb.points)
        ), pa.closed)
        for pa, pb in zip(a.paths, b.paths)
    ))


def _cell_mean(gray, alpha, origin, a, b, inv):
    """Mean (gray, alpha) over the pixels whose centres fall inside the
    lattice parallelogram at origin. Off-page cells cost only the bbox."""
    corners = np.asarray([origin, origin + a, origin + a + b, origin + b])
    x0 = max(0, int(math.floor(corners[:, 0].min())))
    y0 = max(0, int(math.floor(corners[:, 1].min())))
    x1 = min(gray.shape[1], int(math.ceil(corners[:, 0].max())))
    y1 = min(gray.shape[0], int(math.ceil(corners[:, 1].max())))
    if x1 <= x0 or y1 <= y0:
        return 1.0, 0.0
    yy, xx = np.mgrid[y0:y1, x0:x1]
    sample = np.stack((xx + 0.5 - origin[0], yy + 0.5 - origin[1]), axis=-1)
    uv = sample @ inv.T
    mask = ((uv[..., 0] >= 0) & (uv[..., 0] < 1)
            & (uv[..., 1] >= 0) & (uv[..., 1] < 1))
    if not mask.any():
        return 1.0, 0.0
    return float(gray[y0:y1, x0:x1][mask].mean()), float(alpha[y0:y1, x0:x1][mask].mean())


def _transformed_lattice(pattern, width, columns, rotation):
    base_a = np.asarray(pattern.a, dtype=float)
    base_b = np.asarray(pattern.b, dtype=float)
    scale = width / (max(1, int(columns)) * np.linalg.norm(base_a))
    theta = math.radians(float(rotation))
    rot = np.asarray(((math.cos(theta), -math.sin(theta)),
                      (math.sin(theta), math.cos(theta))))
    return rot @ (base_a * scale), rot @ (base_b * scale), rot * scale


def render_tessellation(work: Image.Image, pattern: TessellationPattern,
                        values: dict) -> list[Item]:
    gray, alpha = luminance(work)
    height, width = gray.shape
    a, b, artwork_transform = _transformed_lattice(
        pattern, width, values["columns"], values["rotation"])
    basis = np.column_stack((a, b))
    # Rotation-invariant guard: page area over cell area estimates the number
    # of cells that actually touch the page, so rotating never trips it.
    if width * height / abs(np.linalg.det(basis)) > MAX_TILES:
        raise ValueError(f"Tessellation exceeds the {MAX_TILES:,} tile limit")
    inv = np.linalg.inv(basis)
    phase = float(values["phase_x"]) * a + float(values["phase_y"]) * b
    page = np.asarray(((0, 0), (width, 0), (width, height), (0, height))) - phase
    ij = page @ inv.T
    imin, jmin = np.floor(ij.min(axis=0)).astype(int) - 2
    imax, jmax = np.ceil(ij.max(axis=0)).astype(int) + 2
    items = []
    for i in range(imin, imax + 1):
        for j in range(jmin, jmax + 1):
            origin = phase + i * a + j * b
            mean, cover = _cell_mean(gray, alpha, origin, a, b, inv)
            if cover < ALPHA_COVER_MIN:
                continue
            darkness = 1.0 - mean
            mapped = 1.0 - darkness if values["invert_tone"] else darkness
            mapped = max(0.0, min(1.0, mapped)) ** float(values["tone_response"])
            tile = state_at_tone(pattern, mapped)
            for path in tile.paths:
                points = [tuple(origin + artwork_transform @ np.asarray(p, dtype=float))
                          for p in path.points]
                if len(points) >= 2:
                    items.append(Item(lum=darkness * cover,
                                      path=Geometry(points, closed=path.closed)))
    return deduplicate_items(items) if values["remove_duplicates"] else items


def deduplicate_items(items: list[Item], tolerance: float = 1e-6) -> list[Item]:
    """Drop segments drawn more than once (either direction), then rechain.

    Endpoints are snapped to one representative point per tolerance bucket so
    segments from neighbouring tiles — equal up to float epsilon — compare
    and weld exactly."""
    from .chain import chain_items

    def key(point):
        return tuple(round(float(v) / tolerance) for v in point)

    reps: dict = {}
    segments: dict = {}
    for item in items:
        if item.path is None or len(item.path.points) < 2:
            continue
        points = list(item.path.points)
        if item.path.closed:
            points.append(points[0])
        for p0, p1 in zip(points, points[1:]):
            k0, k1 = key(p0), key(p1)
            r0 = reps.setdefault(k0, (float(p0[0]), float(p0[1])))
            r1 = reps.setdefault(k1, (float(p1[0]), float(p1[1])))
            canonical = (k0, k1) if k0 <= k1 else (k1, k0)
            segments.setdefault(canonical, []).append((item.lum, r0, r1))
    survivors = []
    for occurrences in segments.values():
        lum, p0, p1 = occurrences[0]
        if p0 != p1:
            survivors.append(Item(lum=lum, path=Geometry([p0, p1])))
    return chain_items(survivors, tol=tolerance)
