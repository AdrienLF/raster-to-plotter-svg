"""Shape Dither PFM: registration, tone mapping, aspect, rotation, colours."""

import math

import numpy as np
import pytest
from PIL import Image

from engine import svg_io
from engine.canvas import DrawingArea
from engine.params import validate
from engine.pens import DrawingSet
from engine.pfm import REGISTRY
from engine.pfm.shape_dither import _snapped_rotations, register_shape_pfm
from engine.shape_library import validate_shape_package


def _gradient(width=200, height=100):
    """Horizontal ramp: white on the left, black on the right."""
    row = np.linspace(255, 0, width).astype(np.uint8)
    return Image.fromarray(np.tile(row, (height, 1)), "L").convert("RGB")


def _vals(**overrides):
    pfm = REGISTRY["shape_dither"]
    values = {"columns": 10, "min_scale": 0.1, "max_scale": 0.9}
    values.update(overrides)
    return validate(pfm.params, values)


def _run_generate(**overrides):
    work = _gradient()
    return REGISTRY["shape_dither"].generate(work, _vals(**overrides), 0, work.size)


def _size(item):
    x0, y0, x1, y1 = item.path.bbox()
    return max(x1 - x0, y1 - y0)


def test_registered_with_expected_controls():
    pfm = REGISTRY["shape_dither"]
    assert pfm.family == "shape_dither"
    names = {p.name for p in pfm.params}
    assert {"aspect", "columns", "levels", "invert_tone", "tone_response",
            "dither_error", "min_scale", "max_scale", "rotate_with_image",
            "shape_type", "shape_color", "background_enabled",
            "background_color"} <= names
    aspect = next(p for p in pfm.params if p.name == "aspect")
    assert aspect.choices == ["original", "square"]


def test_dark_cells_get_larger_shapes_and_invert_flips_it():
    items = _run_generate()
    mid = 100
    left = [_size(it) for it in items if it.path.bbox()[0] < mid]
    right = [_size(it) for it in items if it.path.bbox()[0] >= mid]
    assert np.mean(right) > np.mean(left)

    inverted = _run_generate(invert_tone=True)
    left_inv = [_size(it) for it in inverted if it.path.bbox()[0] < mid]
    right_inv = [_size(it) for it in inverted if it.path.bbox()[0] >= mid]
    assert np.mean(left_inv) > np.mean(right_inv)


def test_levels_bound_the_number_of_distinct_sizes():
    items = _run_generate(levels=2)
    sizes = {round(_size(it), 3) for it in items}
    assert 1 <= len(sizes) <= 2

    items = _run_generate(levels=8)
    sizes = {round(_size(it), 3) for it in items}
    assert len(sizes) > 2


def test_square_aspect_keeps_geometry_in_the_centered_window():
    items = _run_generate(aspect="square", max_scale=1.0)
    assert items
    for it in items:
        x0, _, x1, _ = it.path.bbox()
        assert x0 >= 50 - 1e-6
        assert x1 <= 150 + 1e-6


def test_rotations_snap_to_quarter_turns():
    rows = np.linspace(0.0, 1.0, 8)
    darkness = np.tile(rows.reshape(-1, 1), (1, 6))
    rot = _snapped_rotations(darkness)
    quarter = rot / (math.pi / 2)
    assert np.allclose(quarter, np.rint(quarter))
    assert np.all((rot >= 0) & (rot < 2 * math.pi))
    # A pure vertical ramp has a vertical gradient everywhere.
    assert np.any(rot != 0)


def test_dither_error_diffusion_still_quantizes_to_levels():
    items = _run_generate(levels=3, dither_error=True)
    sizes = {round(_size(it), 3) for it in items}
    assert 1 <= len(sizes) <= 3


def test_shape_colour_reaches_geometry_and_svg():
    items = _run_generate(shape_color="#ff0000")
    assert all(it.path.colour == "#ff0000" for it in items)
    assert all(it.path.fill == "#ff0000" for it in items)


def test_background_rect_exports_but_never_plots():
    pfm = REGISTRY["shape_dither"]
    drawing = pfm.run(_gradient(), DrawingArea(), DrawingSet(),
                      {"columns": 8, "background_enabled": True,
                       "background_color": "#123456"})
    assert drawing.background == "#123456"
    svg = svg_io.to_svg(drawing)
    assert 'data-plot="skip"' in svg
    assert 'fill="#123456"' in svg

    pens = [("Pen 1", "#000000")]
    split = svg_io.split_svg_by_pen(svg, pens)
    total_shapes = sum(part["shapes"] for part in split)
    assert total_shapes == drawing.total()  # background rect not counted

    from web.server import svg_to_polylines
    lines = svg_to_polylines(svg.encode("utf-8"), {"curve_step_mm": 0.5},
                             respect_stop=False)
    # 297mm-wide page rect would produce a ~594+ mm perimeter polyline; ensure
    # no polyline spans the full page width.
    for line in lines:
        xs = [x for x, _ in line]
        assert max(xs) - min(xs) < 290


def test_background_disabled_by_default():
    pfm = REGISTRY["shape_dither"]
    drawing = pfm.run(_gradient(), DrawingArea(), DrawingSet(), {"columns": 8})
    assert drawing.background is None
    assert 'data-plot' not in svg_io.to_svg(drawing)


def test_cell_limit_guard():
    tall = _gradient(width=100, height=4000)  # 160 cols -> 6400 rows
    pfm = REGISTRY["shape_dither"]
    with pytest.raises(ValueError, match="cell limit"):
        pfm.generate(tall, _vals(columns=160), 0, tall.size)


# --------------------------------------------------------------------------
# Custom shapes
# --------------------------------------------------------------------------

STROKED = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
           '<path d="M0 5 L10 5" fill="none" stroke="#00aa00"/></svg>')
FILLED = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
          '<rect x="1" y="1" width="8" height="8" fill="#aa0000" stroke="none"/></svg>')


def _custom_pfm(states, name="Test Shape"):
    manifest = {"format_version": 1, "name": name,
                "state_count": len(states), "bounds": [0, 0, 10, 10]}
    shape = validate_shape_package(manifest, states)
    return register_shape_pfm(shape)


def test_custom_shape_registers_and_keeps_source_colours():
    pfm = _custom_pfm([FILLED], name="Filled Square")
    assert pfm.id == "shape_dither_custom_filled_square"
    assert pfm.id in REGISTRY
    names = {p.name for p in pfm.params}
    assert "use_source_colors" in names
    assert "shape_type" not in names

    work = _gradient()
    items = pfm.generate(work, validate(pfm.params, {"columns": 10}), 0, work.size)
    assert items
    assert all(it.path.fill == "#aa0000" for it in items)
    assert all(it.path.colour == "none" for it in items)


def test_custom_shape_recolours_when_source_colours_off():
    pfm = _custom_pfm([STROKED], name="Stroked Line")
    work = _gradient()
    items = pfm.generate(
        work, validate(pfm.params, {"columns": 10, "use_source_colors": False,
                                    "shape_color": "#0000ff"}), 0, work.size)
    assert all(it.path.colour == "#0000ff" for it in items)
    assert all(it.path.fill is None for it in items)


def test_multi_state_shape_picks_states_by_tone():
    horizontal = STROKED
    vertical = STROKED.replace('d="M0 5 L10 5"', 'd="M5 0 L5 10"')
    pfm = _custom_pfm([horizontal, vertical], name="Sweep")
    work = _gradient()
    items = pfm.generate(work, validate(pfm.params, {"columns": 10, "levels": 2}),
                         0, work.size)
    # State 0 (light, left half) is a horizontal line; state 1 (dark, right
    # half) is vertical.
    for it in items:
        x0, y0, x1, y1 = it.path.bbox()
        if (x0 + x1) / 2 < 100:
            assert x1 - x0 > y1 - y0
        else:
            assert y1 - y0 > x1 - x0


def test_custom_shape_runs_end_to_end():
    pfm = _custom_pfm([FILLED], name="E2E Square")
    drawing = pfm.run(_gradient(), DrawingArea(), DrawingSet(), {"columns": 8})
    assert drawing.total() > 0
