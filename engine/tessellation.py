from __future__ import annotations

from dataclasses import dataclass
import math

Point = tuple[float, float]
STATE_COUNT = 32


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
    curve: dict | None = None


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
