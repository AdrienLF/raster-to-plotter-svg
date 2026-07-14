"""Custom dither-shape package validation and library persistence."""

import pytest

from engine.shape_library import (
    ShapeLibrary,
    ShapeValidationError,
    parse_shape_state_svg,
    slugify_shape_name,
    validate_shape_package,
)

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
       '<path d="M0 0 L100 100" fill="none" stroke="#ff0000"/></svg>')
FILLED = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
          '<rect x="10" y="10" width="80" height="80" fill="#00ff00" stroke="none"/></svg>')


def manifest(name="My Shape", state_count=1, bounds=None):
    return {"format_version": 1, "name": name,
            "state_count": state_count, "bounds": bounds}


def test_slug_is_stable_and_prefixed():
    assert slugify_shape_name("  Möbius Dot! ") == "shape_dither_custom_mobius_dot"


def test_parse_keeps_stroke_and_fill_colours():
    paths = parse_shape_state_svg(SVG)
    _points, _closed, stroke, fill = paths[0]
    assert stroke == "#ff0000"
    assert fill is None

    paths = parse_shape_state_svg(FILLED)
    _points, closed, stroke, fill = paths[0]
    assert closed
    assert stroke is None
    assert fill == "#00ff00"


def test_points_are_normalized_centered_with_uniform_scale():
    shape = validate_shape_package(manifest(), [SVG])
    pts = shape.states[0].paths[0].points
    assert pts[0] == pytest.approx((-0.5, -0.5))
    assert pts[-1] == pytest.approx((0.5, 0.5))


def test_bounds_derived_from_artwork_preserve_aspect():
    wide = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
            '<path d="M0 0 L200 50" fill="none" stroke="black"/></svg>')
    shape = validate_shape_package(manifest(), [wide])
    xs = [x for x, _ in shape.states[0].paths[0].points]
    ys = [y for _, y in shape.states[0].paths[0].points]
    # Uniform scale: x spans the full unit box, y only a quarter of it.
    assert max(xs) - min(xs) == pytest.approx(1.0)
    assert max(ys) - min(ys) == pytest.approx(0.25)


def test_dense_curves_are_simplified_but_faithful():
    # A circle flattened at FLATTEN_STEP in tiny source units explodes into
    # thousands of chords; every grid cell stamps a full copy, so the shape
    # must be decimated to stay plottable (RDP in normalized space).
    dense = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 5 5">'
             '<circle cx="2.5" cy="2.5" r="2" fill="none" stroke="black"/></svg>')
    shape = validate_shape_package(manifest(), [dense])
    pts = shape.states[0].paths[0].points
    assert len(pts) < 200
    # Bounds derive from the artwork (the circle itself), so every kept point
    # still lies on the normalized circle of radius 0.5.
    for x, y in pts:
        assert (x * x + y * y) ** 0.5 == pytest.approx(0.5, abs=0.005)


def test_reload_simplifies_pre_existing_dense_packages(tmp_path):
    import json
    library = ShapeLibrary(tmp_path)
    shape = library.install(manifest("Dense"), [SVG])
    # Rewrite the persisted package with an over-flattened path, as installed
    # before simplification existed.
    entry = tmp_path / shape.id / "shape.json"
    data = json.loads(entry.read_text("utf-8"))
    import math
    ring = [[0.4 * math.cos(i / 2000 * 2 * math.pi),
             0.4 * math.sin(i / 2000 * 2 * math.pi)] for i in range(2000)]
    data["states"] = [{"paths": [{"points": ring, "closed": True,
                                  "stroke": "#000000", "fill": None}]}]
    entry.write_text(json.dumps(data), "utf-8")

    reloaded = ShapeLibrary(tmp_path).get(shape.id)
    assert len(reloaded.states[0].paths[0].points) < 200


def test_validate_enforces_state_count():
    with pytest.raises(ShapeValidationError, match="1 states"):
        validate_shape_package(manifest(state_count=1), [SVG, SVG])
    with pytest.raises(ShapeValidationError, match="state_count"):
        validate_shape_package(manifest(state_count=0), [])
    with pytest.raises(ShapeValidationError, match="state_count"):
        validate_shape_package(manifest(state_count=64), [SVG] * 64)


def test_validate_rejects_active_and_external_svg():
    for body in ("<svg><script>alert(1)</script></svg>",
                 '<svg><image href="https://example.com/x.png"/></svg>'):
        with pytest.raises(ShapeValidationError):
            validate_shape_package(manifest(), [body])


def test_multi_state_package_keeps_state_order():
    states = [SVG.replace('d="M0 0 L100 100"', f'd="M0 0 L100 {10 * (i + 1)}"')
              for i in range(4)]
    shape = validate_shape_package(manifest(state_count=4, bounds=[0, 0, 100, 100]),
                                   states, source="cavalry")
    assert shape.source == "cavalry"
    assert len(shape.states) == 4
    ends = [state.paths[0].points[-1][1] for state in shape.states]
    assert ends == sorted(ends)


def test_install_persists_and_reload_roundtrips(tmp_path):
    library = ShapeLibrary(tmp_path)
    shape = library.install(manifest("Dot"), [FILLED])
    assert shape.id == "shape_dither_custom_dot"
    assert (tmp_path / shape.id / "shape.json").is_file()
    assert (tmp_path / shape.id / "preview.png").is_file()

    reloaded = ShapeLibrary(tmp_path).get(shape.id)
    assert reloaded == shape
    assert reloaded.states[0].paths[0].fill == "#00ff00"
    assert len(library.list()) == 1
    assert library.list()[0]["states"] == 1


def test_failed_replace_preserves_previous_package(tmp_path, monkeypatch):
    library = ShapeLibrary(tmp_path)
    original = library.install(manifest("Dot"), [SVG])
    before = (tmp_path / original.id / "shape.json").read_bytes()
    monkeypatch.setattr(library, "_atomic_replace",
                        lambda *args: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        library.install(manifest("Dot"), [SVG])
    assert (tmp_path / original.id / "shape.json").read_bytes() == before
