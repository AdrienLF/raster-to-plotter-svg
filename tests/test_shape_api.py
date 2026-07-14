"""Transactional API coverage for dither-shape uploads and Cavalry bakes."""

import io

import pytest
from PIL import Image

from engine.pfm import REGISTRY, get as get_pfm
from engine.pfm.base import generate_items
from engine.shape_library import ShapeLibrary
import web.server as server


SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<path d="M0 0 L100 100" fill="none" stroke="#ff0000"/>'
    '</svg>'
)


def manifest(name="My Shape", state_count=4):
    return {
        "format_version": 1,
        "name": name,
        "state_count": state_count,
        "bounds": [0, 0, 100, 100],
    }


@pytest.fixture
def isolated_library(tmp_path, monkeypatch):
    library = ShapeLibrary(tmp_path / "shapes")
    monkeypatch.setattr(server, "_shape_library", library, raising=False)
    previous_custom_pfms = {
        pfm_id: pfm
        for pfm_id, pfm in REGISTRY.items()
        if pfm_id.startswith("shape_dither_custom_")
    }
    yield library
    for pfm_id in list(REGISTRY):
        if pfm_id.startswith("shape_dither_custom_"):
            REGISTRY.pop(pfm_id, None)
    REGISTRY.update(previous_custom_pfms)


@pytest.fixture
def session_root(tmp_path, monkeypatch):
    root = tmp_path / "shape-sessions"
    monkeypatch.setattr(server, "_shape_session_root", root, raising=False)
    return root


@pytest.fixture
def client(isolated_library, session_root):
    return server.app.test_client()


def test_direct_upload_installs_and_registers(client, isolated_library):
    response = client.post(
        "/api/shapes",
        data={"file": (io.BytesIO(SVG.encode("utf-8")), "My Arrow.svg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["shape"]["id"] == "shape_dither_custom_my_arrow"
    assert payload["shape"]["source"] == "upload"
    assert "shape_dither_custom_my_arrow" in REGISTRY
    assert any(p["id"] == "shape_dither_custom_my_arrow" for p in payload["pfms"])
    assert isolated_library.list()[0]["states"] == 1


def test_upload_rejects_non_svg_and_invalid_svg(client, isolated_library):
    registered_before = {k for k in REGISTRY if k.startswith("shape_dither_custom_")}
    response = client.post(
        "/api/shapes",
        data={"file": (io.BytesIO(b"not svg"), "shape.png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400

    response = client.post(
        "/api/shapes",
        data={"file": (io.BytesIO(b"<svg><script>x</script></svg>"), "evil.svg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert isolated_library.list() == []
    registered_after = {k for k in REGISTRY if k.startswith("shape_dither_custom_")}
    assert registered_after == registered_before


def test_session_create_requires_valid_state_count(client):
    bad = manifest(state_count=0)
    assert client.post("/api/shapes/sessions", json=bad).status_code == 400
    bad = manifest(state_count=64)
    assert client.post("/api/shapes/sessions", json=bad).status_code == 400


def test_complete_session_installs_and_registers(client, isolated_library):
    sid = client.post("/api/shapes/sessions", json=manifest()).get_json()["session_id"]
    for index in range(4):
        response = client.post(
            f"/api/shapes/sessions/{sid}/states/{index}",
            data=SVG,
            content_type="image/svg+xml",
        )
        assert response.status_code == 200
    result = client.post(f"/api/shapes/sessions/{sid}/finalize")
    assert result.status_code == 200
    payload = result.get_json()
    assert payload["shape"]["id"] == "shape_dither_custom_my_shape"
    assert payload["shape"]["source"] == "cavalry"
    assert "shape_dither_custom_my_shape" in REGISTRY
    assert isolated_library.list()[0]["states"] == 4


def test_out_of_range_duplicate_and_missing_states(client, isolated_library):
    sid = client.post("/api/shapes/sessions", json=manifest()).get_json()["session_id"]
    assert client.post(f"/api/shapes/sessions/{sid}/states/4", data=SVG).status_code == 400
    assert client.post(f"/api/shapes/sessions/{sid}/states/0", data=SVG).status_code == 200
    assert client.post(f"/api/shapes/sessions/{sid}/states/0", data=SVG).status_code == 409
    response = client.post(f"/api/shapes/sessions/{sid}/finalize")
    assert response.status_code == 400
    assert isolated_library.list() == []


def test_installed_shape_is_discoverable_and_generates(client):
    response = client.post(
        "/api/shapes",
        data={"file": (io.BytesIO(SVG.encode("utf-8")), "flow.svg")},
        content_type="multipart/form-data",
    )
    pfm_id = response.get_json()["shape"]["id"]

    listed = client.get("/api/pfm/list").get_json()["pfms"]
    assert any(item["id"] == pfm_id and item["family"] == "shape_dither"
               for item in listed)
    schema = client.get(f"/api/pfm/{pfm_id}/schema").get_json()
    names = {param["name"] for param in schema["params"]}
    assert {"columns", "levels", "invert_tone", "min_scale", "max_scale",
            "rotate_with_image", "use_source_colors", "shape_color"} <= names
    color_param = next(p for p in schema["params"] if p["name"] == "shape_color")
    assert color_param["type"] == "color"

    preview = client.get(f"/static/pfm-previews/{pfm_id}.png")
    assert preview.status_code == 200
    assert preview.mimetype == "image/png"

    items = generate_items(
        get_pfm(pfm_id), Image.new("RGB", (48, 48), "gray"), {"columns": 6}, 0, (48, 48)
    )
    assert any(item.path is not None for item in items)


def test_shapes_list_endpoint(client, isolated_library):
    isolated_library.install(
        {"format_version": 1, "name": "Listed", "state_count": 1, "bounds": None},
        [SVG])
    response = client.get("/api/shapes")
    assert response.status_code == 200
    assert response.get_json()["shapes"][0]["id"] == "shape_dither_custom_listed"


def test_builtin_previews_are_served(client):
    preview = client.get("/static/pfm-previews/dither_halftone.png")
    assert preview.status_code == 200
    assert preview.mimetype == "image/png"
