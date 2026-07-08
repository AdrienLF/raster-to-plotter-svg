"""Built-in tessellation state atlases.

Each factory maps t in 0-1 (light -> dark) to one deterministic TileState;
32 samples of it form the pattern's state atlas. Artwork lives in the unit
square and is placed on the pattern's lattice by the renderer.
"""

from __future__ import annotations

import math

from .tessellation import STATE_COUNT, TessellationPattern, TilePath, TileState

SQRT3_2 = math.sqrt(3.0) / 2.0


def _poly(points, closed=False) -> TilePath:
    return TilePath(tuple((float(x), float(y)) for x, y in points), closed)


def _arc(cx, cy, radius, start, end, count=12):
    return tuple(
        (cx + radius * math.cos(math.radians(start + (end - start) * k / (count - 1))),
         cy + radius * math.sin(math.radians(start + (end - start) * k / (count - 1))))
        for k in range(count)
    )


def _states(factory) -> tuple[TileState, ...]:
    return tuple(factory(i / (STATE_COUNT - 1)) for i in range(STATE_COUNT))


def _isometric_y(t):
    # One closed Y-block outline: three chevron-tipped arms joined at armpit
    # crotches. Arms from the three tiles around each triangular hole aim at
    # its centroid, 1/sqrt(3) lattice units from every tile centre; light
    # tiles interlock there while dark tiles thin out and pull back, opening
    # the triangular gaps seen in the reference weave.
    w = 0.26 - 0.16 * t
    outer = 1.0 / math.sqrt(3.0) - 0.10 * t
    corner = outer - w / math.tan(math.radians(60))
    crotch = w / math.sin(math.radians(60))
    points = []
    seams = []
    for angle in (-90, 30, 150):
        a = math.radians(angle)
        dx, dy = math.cos(a), math.sin(a)
        px, py = -dy, dx
        bis = math.radians(angle - 60)
        armpit = (0.5 + crotch * math.cos(bis), 0.5 + crotch * math.sin(bis))
        points.append(armpit)
        points.append((0.5 + corner * dx - w * px, 0.5 + corner * dy - w * py))
        points.append((0.5 + outer * dx, 0.5 + outer * dy))
        points.append((0.5 + corner * dx + w * px, 0.5 + corner * dy + w * py))
        # Internal facet seam of the 3D block: centre vertex to each crotch.
        seams.append(_poly(((0.5, 0.5), armpit)))
    return TileState((_poly(points, True), *seams))


def _hex_aperture(t):
    r = 0.12 + 0.32 * t
    points = tuple((0.5 + r * math.cos(math.radians(60 * i - 30)),
                    0.5 + r * math.sin(math.radians(60 * i - 30))) for i in range(6))
    return TileState((_poly(points, True),))


def _truchet_weave(t):
    offset = 0.06 + 0.10 * t
    return TileState((
        _poly(_arc(0, 0, 0.5 - offset, 0, 90)),
        _poly(_arc(1, 1, 0.5 + offset, 180, 270)),
        _poly(_arc(1, 0, 0.5 - offset, 90, 180)),
        _poly(_arc(0, 1, 0.5 + offset, 270, 360)),
    ))


def _diamond_lattice(t):
    rx, ry = 0.16 + 0.30 * t, 0.46 - 0.20 * t
    return TileState((_poly(((0.5, 0.5 - ry), (0.5 + rx, 0.5),
                             (0.5, 0.5 + ry), (0.5 - rx, 0.5)), True),))


def _pattern(pattern_id, name, a, b, factory) -> TessellationPattern:
    return TessellationPattern(
        id=pattern_id, name=name, source="builtin",
        a=a, b=b, bounds=(0.0, 0.0, 1.0, 1.0),
        states=_states(factory), bindings=(),
    )


BUILTIN_PATTERNS: dict[str, TessellationPattern] = {
    p.id: p for p in (
        _pattern("tessellation_isometric_y", "Isometric Y",
                 (1.0, 0.0), (0.5, SQRT3_2), _isometric_y),
        _pattern("tessellation_hex_aperture", "Hex Aperture",
                 (1.0, 0.0), (0.5, SQRT3_2), _hex_aperture),
        _pattern("tessellation_truchet_weave", "Truchet Weave",
                 (1.0, 0.0), (0.0, 1.0), _truchet_weave),
        _pattern("tessellation_diamond_lattice", "Diamond Lattice",
                 (1.0, 0.5), (-1.0, 0.5), _diamond_lattice),
    )
}
