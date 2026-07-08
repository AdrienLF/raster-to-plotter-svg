"""Tessellation pattern model, renderer, and duplicate removal."""

import numpy as np
import pytest
from PIL import Image

from engine.geometry import Geometry, Item
from engine.tessellation import (
    ParameterBinding,
    TessellationPattern,
    TilePath,
    TileState,
    deduplicate_items,
    render_tessellation,
    state_at_tone,
)


def state(x, *, closed=False, points=2):
    pts = tuple((x + i, x) for i in range(points))
    return TileState((TilePath(pts, closed),))


def pattern(states):
    return TessellationPattern(
        id="test", name="Test", source="builtin",
        a=(1.0, 0.0), b=(0.0, 1.0), bounds=(0.0, 0.0, 1.0, 1.0),
        states=tuple(states), bindings=(),
    )


def test_pattern_requires_32_states_and_nondegenerate_lattice():
    with pytest.raises(ValueError, match="32 states"):
        pattern([state(0.0)])
    with pytest.raises(ValueError, match="non-collinear"):
        TessellationPattern(
            id="bad", name="Bad", source="builtin",
            a=(1.0, 0.0), b=(2.0, 0.0), bounds=(0, 0, 1, 1),
            states=tuple(state(0.0) for _ in range(32)), bindings=(),
        )


def test_state_at_tone_interpolates_compatible_neighbors():
    p = pattern([state(float(i)) for i in range(32)])
    out = state_at_tone(p, 0.5)
    assert out.paths[0].points[0] == pytest.approx((15.5, 15.5))


@pytest.mark.parametrize("changed", [
    TileState((TilePath(((16, 16), (17, 16)), True),)),
    TileState((TilePath(((16, 16), (17, 16), (18, 16)), False),)),
    TileState((TilePath(((16, 16), (17, 16)), False), TilePath(((0, 0), (1, 1)), False))),
])
def test_state_at_tone_uses_nearest_whole_state_when_topology_changes(changed):
    states = [state(float(i)) for i in range(32)]
    states[16] = changed
    p = pattern(states)
    assert state_at_tone(p, 15.75 / 31) == changed


def constant_pattern(path=TilePath(((0.1, 0.5), (0.9, 0.5)))):
    s = TileState((path,))
    return TessellationPattern(
        id="constant", name="Constant", source="builtin",
        a=(1, 0), b=(0, 1), bounds=(0, 0, 1, 1),
        states=tuple(s for _ in range(32)), bindings=(),
    )


VALUES = dict(columns=2, rotation=0, phase_x=0, phase_y=0,
              tone_response=1, invert_tone=False, remove_duplicates=False)


def test_render_covers_page_and_scales_by_columns():
    work = Image.new("L", (100, 60), 128)
    items = render_tessellation(work, constant_pattern(), VALUES)
    # 2 columns x 2 rows of cells intersect the 100x60 page.
    assert len(items) == 4
    assert all(item.path is not None for item in items)
    xs = [x for item in items for x, _ in item.path.points]
    ys = [y for item in items for _, y in item.path.points]
    assert min(xs) < 10 and max(xs) > 90
    assert max(ys) > work.height  # partial bottom row still draws
    more = render_tessellation(work, constant_pattern(), {**VALUES, "columns": 4})
    assert len(more) > len(items)


def test_render_skips_transparent_cells():
    work = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    assert render_tessellation(work, constant_pattern(), VALUES) == []


def test_render_applies_gamma_and_inversion_to_geometry():
    states = tuple(state(float(i) / 31) for i in range(32))
    p = TessellationPattern("tone", "Tone", "builtin", (1, 0), (0, 1),
                            (0, 0, 1, 1), states, ())
    work = Image.fromarray(np.full((20, 20), 64, np.uint8), "L")
    normal = render_tessellation(work, p, {**VALUES, "columns": 1})[0]
    inverted = render_tessellation(work, p, {**VALUES, "columns": 1,
                                             "invert_tone": True})[0]
    assert normal.path.points != inverted.path.points
    assert normal.lum == pytest.approx(1 - 64 / 255, abs=0.02)


def test_rotation_and_phase_change_geometry_while_covering_page():
    work = Image.new("L", (80, 60), 128)
    base = render_tessellation(work, constant_pattern(), VALUES)
    moved = render_tessellation(
        work, constant_pattern(),
        {**VALUES, "rotation": 17, "phase_x": 0.25, "phase_y": -0.2},
    )
    assert base and moved
    assert moved[0].path.points != base[0].path.points
    for items in (base, moved):
        xs = [x for item in items for x, _ in item.path.points]
        ys = [y for item in items for _, y in item.path.points]
        assert min(xs) < work.width / 2 < max(xs)
        assert min(ys) < work.height / 2 < max(ys)


def test_render_rejects_absurd_tile_counts():
    huge = Image.new("L", (4000, 4000), 128)
    with pytest.raises(ValueError, match="tile limit"):
        render_tessellation(huge, constant_pattern(), {**VALUES, "columns": 300})


def test_duplicate_segments_are_removed_regardless_of_direction():
    items = [
        Item(0.2, path=Geometry([(0, 0), (1, 0), (2, 0)])),
        Item(0.8, path=Geometry([(2, 0), (1, 0)])),
    ]
    out = deduplicate_items(items)
    segments = [
        tuple(sorted((p0, p1)))
        for item in out if item.path
        for p0, p1 in zip(item.path.points, item.path.points[1:])
    ]
    assert segments.count(tuple(sorted(((1.0, 0.0), (2.0, 0.0))))) == 1
    assert segments.count(tuple(sorted(((0.0, 0.0), (1.0, 0.0))))) == 1


def test_nearby_but_distinct_segments_survive():
    items = [
        Item(0.5, path=Geometry([(0, 0), (1, 0)])),
        Item(0.5, path=Geometry([(0, 0.01), (1, 0.01)])),
    ]
    assert len(deduplicate_items(items, tolerance=1e-4)) == 2


def test_deduplicate_rechains_across_epsilon_endpoint_noise():
    eps = 1e-9
    items = [
        Item(0.5, path=Geometry([(0, 0), (1, 0)])),
        Item(0.5, path=Geometry([(1 + eps, eps), (2, 0)])),
    ]
    out = deduplicate_items(items)
    assert len(out) == 1
    assert len(out[0].path.points) == 3
