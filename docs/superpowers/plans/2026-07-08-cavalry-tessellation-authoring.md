# Cavalry Tessellation Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Cavalry bridge bake one or more selected numeric parameters into a reusable 32-state tessellation pattern installed in PlotterForge.

**Architecture:** A filesystem-backed `TessellationLibrary` validates and atomically stores normalized pattern packages, then registers them through the core plan's `register_tessellation_pattern`. Flask endpoints stage a manifest and 32 raw SVG states transactionally; the Cavalry script uses documented selected-attribute, value, render, file, and WebClient APIs to drive the bake.

**Tech Stack:** Python 3.13, Flask, svgelements, Pillow, Cavalry JavaScript UI/API, pytest, Node syntax validation.

## Global Constraints

- This plan begins only after `2026-07-08-raster-driven-tessellation-core.md` is complete.
- Exactly 32 states are required; at most 16 linked scalar numeric parameters are accepted.
- Limits are 8 MiB per SVG, 128 MiB total, 2,000 paths and 200,000 flattened points per state, coordinate magnitude 1,000,000, and pattern names of 1–80 visible characters.
- Pattern IDs use the reserved `tessellation_custom_` prefix and a normalized name slug.
- Installation and replacement are atomic; an incomplete bake never registers.
- All original Cavalry values are restored after success or failure.
- A shared linear bake axis is stored now; nullable per-binding curve metadata is retained for future use.

---

### Task 1: SVG-to-tile conversion and package validation

**Files:**
- Create: `engine/tessellation_library.py`
- Create: `tests/test_tessellation_library.py`

**Interfaces:**
- Consumes: `TilePath`, `TileState`, `ParameterBinding`, `TessellationPattern` from `engine.tessellation`.
- Produces: `PatternValidationError`, `slugify_pattern_name(name)`, `parse_state_svg(svg)`, and `validate_package(manifest, states)`.

- [ ] **Step 1: Write failing validation tests**

```python
import pytest

from engine.tessellation_library import (
    PatternValidationError,
    parse_state_svg,
    slugify_pattern_name,
    validate_package,
)

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M0 0 L100 100" fill="none" stroke="black"/></svg>'


def manifest(name="My Pattern"):
    return {
        "format_version": 1, "name": name,
        "lattice": {"a": [100, 0], "b": [0, 100]},
        "bounds": [0, 0, 100, 100],
        "bindings": [{"layer_id": "basicShape#1", "attribute_id": "rotation",
                      "light": 0, "dark": 90, "curve": None}],
    }


def test_slug_is_stable_and_prefixed():
    assert slugify_pattern_name("  Möbius Grid! ") == "tessellation_custom_mobius_grid"


def test_svg_is_flattened_and_normalized_to_bounds():
    state = parse_state_svg(SVG, (0, 0, 100, 100))
    assert state.paths[0].points[0] == pytest.approx((0, 0))
    assert state.paths[0].points[-1] == pytest.approx((1, 1))


def test_validate_requires_32_states_and_valid_lattice():
    with pytest.raises(PatternValidationError, match="32 states"):
        validate_package(manifest(), [SVG])
    bad = manifest()
    bad["lattice"]["b"] = [200, 0]
    with pytest.raises(PatternValidationError, match="non-collinear"):
        validate_package(bad, [SVG] * 32)


def test_validate_rejects_active_and_external_svg():
    for body in ("<svg><script>alert(1)</script></svg>",
                 '<svg><image href="https://example.com/x.png"/></svg>'):
        with pytest.raises(PatternValidationError):
            validate_package(manifest(), [body] * 32)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/test_tessellation_library.py -q`

Expected: import fails because `engine.tessellation_library` is absent.

- [ ] **Step 3: Implement strict manifest/SVG validation**

Implement the declared functions with these concrete rules:

```python
FORMAT_VERSION = 1
STATE_COUNT = 32
MAX_SVG_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_PATHS = 2_000
MAX_POINTS = 200_000
MAX_BINDINGS = 16
MAX_COORD = 1_000_000
FORBIDDEN_TAGS = {"script", "image", "foreignObject", "use"}
FORBIDDEN_ATTRS = {"href", "xlink:href", "onload", "onclick"}
```

Parse XML with `xml.etree.ElementTree`, reject forbidden local tag/attribute
names before passing content to `svgelements.SVG.parse`. Flatten `Path`,
`Polyline`, `Polygon`, `Line`, `Rect`, `Circle`, and `Ellipse` with a maximum
step of `0.4` source units, apply element transforms, normalize by manifest
bounds, and enforce path/point/coordinate limits while building `TileState`.
Reject booleans as numeric values, non-finite values, duplicate bindings,
empty states, invalid bounds, and degenerate lattice vectors. Return a complete
`TessellationPattern` whose vectors and state points are divided by bounds width
and height.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `uv run pytest tests/test_tessellation_library.py -q`

Expected: all validation tests pass.

- [ ] **Step 5: Commit validation**

```bash
git add engine/tessellation_library.py tests/test_tessellation_library.py
git commit -m "feat: validate custom tessellation packages"
```

---

### Task 2: Atomic custom-pattern library and dynamic registration

**Files:**
- Modify: `engine/tessellation_library.py`
- Modify: `engine/pfm/tessellation.py`
- Modify: `tests/test_tessellation_library.py`

**Interfaces:**
- Produces: `TessellationLibrary(root: Path)`, with `install(manifest, states)`, `list()`, `load_all()`, and `get(pattern_id)`.
- Produces: `replace_tessellation_pattern(pattern)` in `engine.pfm.tessellation`; replacement assigns the stable PFM ID in `REGISTRY` without changing existing rendered SVG layers.

- [ ] **Step 1: Add failing atomic storage tests**

```python
def test_install_persists_and_replaces_atomically(tmp_path):
    library = TessellationLibrary(tmp_path)
    first = library.install(manifest("Grid"), [SVG] * 32)
    assert first.id == "tessellation_custom_grid"
    assert (tmp_path / first.id / "pattern.json").is_file()
    changed = manifest("Grid")
    changed["bindings"][0]["dark"] = 180
    second = library.install(changed, [SVG] * 32)
    assert second.bindings[0].dark == 180
    assert len(library.list()) == 1


def test_failed_replace_preserves_previous_package(tmp_path, monkeypatch):
    library = TessellationLibrary(tmp_path)
    original = library.install(manifest("Grid"), [SVG] * 32)
    before = (tmp_path / original.id / "pattern.json").read_bytes()
    monkeypatch.setattr(library, "_atomic_replace", lambda *args: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        library.install(manifest("Grid"), [SVG] * 32)
    assert (tmp_path / original.id / "pattern.json").read_bytes() == before


def test_load_all_isolates_corrupt_entries(tmp_path):
    library = TessellationLibrary(tmp_path)
    good = library.install(manifest("Good"), [SVG] * 32)
    (tmp_path / "tessellation_custom_bad").mkdir()
    (tmp_path / "tessellation_custom_bad" / "pattern.json").write_text("{")
    assert [p.id for p in library.load_all()] == [good.id]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/test_tessellation_library.py -q`

Expected: `TessellationLibrary` is absent.

- [ ] **Step 3: Implement JSON persistence, previews, and registry replacement**

Serialize the normalized dataclasses to `pattern.json`, render `preview.png` at
105×148 from a vertical gradient through `render_tessellation(columns=10)`, and
write both into a sibling staging directory. Flush files, rename the current
entry to a backup, rename staging to the stable ID, then remove the backup;
restore the backup if the second rename fails. `load_all()` logs and skips an
invalid directory. `list()` returns sorted `{id, name, source, updated_at}`
records.

Add to `engine/pfm/tessellation.py`:

```python
def replace_tessellation_pattern(pattern: TessellationPattern) -> PFM:
    return register_tessellation_pattern(pattern)
```

The existing `register()` assignment provides replacement semantics for the
same stable ID.

- [ ] **Step 4: Run library, PFM, and preview tests**

Run: `uv run pytest tests/test_tessellation_library.py tests/test_tessellation_pfm.py -q`

Expected: all tests pass and generated previews are valid 105×148 PNGs.

- [ ] **Step 5: Commit library persistence**

```bash
git add engine/tessellation_library.py engine/pfm/tessellation.py tests/test_tessellation_library.py
git commit -m "feat: persist custom tessellation library"
```

---

### Task 3: Transactional Flask bake sessions

**Files:**
- Modify: `web/server.py`
- Create: `tests/test_tessellation_api.py`

**Interfaces:**
- `POST /api/tessellations/sessions` accepts the JSON manifest and returns `{session_id}`.
- `POST /api/tessellations/sessions/<session_id>/states/<index>` accepts raw `image/svg+xml`.
- `POST /api/tessellations/sessions/<session_id>/finalize` installs and returns `{ok, pattern, pfms}`.
- `GET /api/tessellations` returns `{patterns}`.

- [ ] **Step 1: Write failing endpoint tests**

```python
def test_complete_session_installs_and_registers(client, isolated_library):
    created = client.post("/api/tessellations/sessions", json=manifest()).get_json()
    sid = created["session_id"]
    for index in range(32):
        response = client.post(f"/api/tessellations/sessions/{sid}/states/{index}",
                               data=SVG, content_type="image/svg+xml")
        assert response.status_code == 200
    result = client.post(f"/api/tessellations/sessions/{sid}/finalize")
    assert result.status_code == 200
    assert result.get_json()["pattern"]["id"] == "tessellation_custom_my_pattern"
    assert "tessellation_custom_my_pattern" in REGISTRY


def test_finalize_missing_state_is_non_destructive(client, isolated_library):
    sid = client.post("/api/tessellations/sessions", json=manifest()).get_json()["session_id"]
    client.post(f"/api/tessellations/sessions/{sid}/states/0", data=SVG,
                content_type="image/svg+xml")
    response = client.post(f"/api/tessellations/sessions/{sid}/finalize")
    assert response.status_code == 400
    assert isolated_library.list() == []


def test_duplicate_and_out_of_range_states_are_rejected(client):
    sid = client.post("/api/tessellations/sessions", json=manifest()).get_json()["session_id"]
    assert client.post(f"/api/tessellations/sessions/{sid}/states/32", data=SVG).status_code == 400
    assert client.post(f"/api/tessellations/sessions/{sid}/states/0", data=SVG).status_code == 200
    assert client.post(f"/api/tessellations/sessions/{sid}/states/0", data=SVG).status_code == 409


def test_expired_session_is_removed(client, session_root, monkeypatch):
    sid = client.post("/api/tessellations/sessions", json=manifest()).get_json()["session_id"]
    monkeypatch.setattr("web.server.time.time", lambda: 7_200)
    (session_root / sid / "created_at").write_text("0")
    response = client.post(f"/api/tessellations/sessions/{sid}/states/0", data=SVG)
    assert response.status_code == 404
    assert not (session_root / sid).exists()
```

- [ ] **Step 2: Run API tests and verify RED**

Run: `uv run pytest tests/test_tessellation_api.py -q`

Expected: all tessellation routes return 404.

- [ ] **Step 3: Implement isolated staging and endpoints**

Create the application library at `WORKSPACE / "tessellations"` and session
root at `WORKSPACE / "tessellation-imports"`. A session directory contains
`manifest.json`, `created_at`, and `state-00.svg` through `state-31.svg`.
Generate session IDs with `uuid.uuid4().hex`, reject unknown/expired sessions,
expire sessions after one hour, enforce per-state and aggregate byte limits
before writes, use exclusive state-file creation, and delete the session after
successful finalization or validation failure. After install, call
`replace_tessellation_pattern(pattern)` and return `list_pfms()` so the client
can refresh discovery without restarting.

At server startup call `library.load_all()` and register each returned pattern;
catch and log each package error separately.

- [ ] **Step 4: Run API and existing Cavalry tests**

Run: `uv run pytest tests/test_tessellation_api.py tests/test_cavalry_bridge.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit transaction endpoints**

```bash
git add web/server.py tests/test_tessellation_api.py
git commit -m "feat: import baked tessellation sessions"
```

---

### Task 4: Cavalry binding-table UI

**Files:**
- Modify: `cavalry/plotter-bridge.js`
- Modify: `tests/test_cavalry_bridge.py`

**Interfaces:**
- Uses Cavalry `api.getSelectedAttributes()`, `api.get(layerId, attrId)`, and `api.getNiceName(layerId)`.
- A binding is `{layerId, attrId, light, dark, curve: null}`.

- [ ] **Step 1: Add failing script-contract tests**

```python
def test_tessellation_ui_adds_selected_numeric_attributes(self):
    self.assertIn('var patternName = new ui.LineEdit();', self.script)
    self.assertIn('var latticePreset = new ui.DropDown();', self.script)
    self.assertIn('var addBinding = new ui.Button("Add selected parameter");', self.script)
    self.assertIn('api.getSelectedAttributes()', self.script)
    self.assertIn('api.get(layerId, attrId)', self.script)
    self.assertIn('new ui.NumericField(value)', self.script)
    self.assertIn('curve: null', self.script)

def test_tessellation_ui_exposes_lattice_presets_and_custom_vectors(self):
    for label in ("Rectangular", "Brick", "Hex/Isometric", "Custom"):
        self.assertIn(f'latticePreset.addEntry("{label}")', self.script)
    for key in ("customAx", "customAy", "customBx", "customBy"):
        self.assertIn(f"var {key} = new ui.NumericField", self.script)
```

- [ ] **Step 2: Run contract tests and verify RED**

Run: `uv run pytest tests/test_cavalry_bridge.py::CavalryScriptContractTest -q`

Expected: the new string contracts are absent.

- [ ] **Step 3: Implement the binding editor with supported Cavalry widgets**

Add a Tessellation separator beneath the existing live-capture controls.
Use `ui.LineEdit`, `ui.DropDown`, `ui.NumericField`, `ui.Button`, `ui.VLayout`,
`ui.HLayout`, `ui.ScrollView`, and `ui.ProgressBar`. `Add selected parameter`
requires exactly one selected attribute pair, reads it with `api.get`, rejects
non-number/non-finite values, rejects duplicates, and appends a row containing
a read-only `Layer · attribute` label, Light and Dark numeric fields initialized
to the current value, and a Remove button. Store row objects in `bindings` and
rebuild the binding layout after removal. Limit additions to 16.

Rectangular derives `A=[width,0], B=[0,height]`; Brick derives
`A=[width,0], B=[width/2,height]`; Hex/Isometric derives
`A=[width,0], B=[width/2,height*0.8660254038]`; Custom reads the four numeric
fields. Read composition resolution with
`api.get(api.getActiveComp(), "resolution")`.

- [ ] **Step 4: Run script checks**

Run:

```bash
uv run pytest tests/test_cavalry_bridge.py::CavalryScriptContractTest -q
node --check cavalry/plotter-bridge.js
```

Expected: contract tests pass and Node reports no syntax error.

- [ ] **Step 5: Commit the authoring UI**

```bash
git add cavalry/plotter-bridge.js tests/test_cavalry_bridge.py
git commit -m "feat: add Cavalry tessellation binding editor"
```

---

### Task 5: Cavalry bake, upload, finalization, and restoration

**Files:**
- Modify: `cavalry/plotter-bridge.js`
- Modify: `tests/test_cavalry_bridge.py`

**Interfaces:**
- Uses documented `api.set`, `api.renderSVGFrame`, `api.readFromFile`, and `api.WebClient.post`.
- Uploads the manifest first, then raw SVG state strings, then finalizes.

- [ ] **Step 1: Add failing bake-loop contracts**

```python
def test_bake_sweeps_32_states_and_restores_in_finally(self):
    self.assertIn("for (var stateIndex = 0; stateIndex < 32; stateIndex++)", self.script)
    self.assertIn("var t = stateIndex / 31;", self.script)
    self.assertIn("binding.light + t * (binding.dark - binding.light)", self.script)
    self.assertIn("api.renderSVGFrame(stateStem, 100, true);", self.script)
    self.assertIn("api.readFromFile(stateStem + '.svg')", self.script)
    self.assertIn("finally", self.script)
    self.assertIn("restoreBindings(originalValues);", self.script)

def test_bake_uses_transaction_endpoints_in_order(self):
    create = self.script.index('client.post("/api/tessellations/sessions"')
    state = self.script.index('"/api/tessellations/sessions/" + sessionId + "/states/"')
    finish = self.script.index('"/api/tessellations/sessions/" + sessionId + "/finalize"')
    self.assertLess(create, state)
    self.assertLess(state, finish)
```

- [ ] **Step 2: Run contract tests and verify RED**

Run: `uv run pytest tests/test_cavalry_bridge.py::CavalryScriptContractTest -q`

Expected: bake-loop and endpoint contracts fail.

- [ ] **Step 3: Implement the synchronous guarded bake**

Validate a non-empty 1–80 character name, at least one binding, finite boundary
values, and a non-zero lattice determinant. Build the manifest JSON with
format version 1, lattice, composition bounds, and all bindings. Create the
server session with `client.post(path, JSON.stringify(manifest),
"application/json")`; parse `session_id` from `client.body()`.

Save originals in an array before mutation. In a `try` block, loop 32 times,
set every bound attribute with an object whose computed key is `attrId`, render
to `api.getTempFolder() + "/plotter-tessellation-" + stateIndex`, read the SVG,
and post it as `image/svg+xml` to the indexed state endpoint. Stop on any
non-200 response. Finalize only after all states succeed. In `finally`, restore
every original value and reset the progress bar. Show `Installed <name>` only
after a 200 finalization; otherwise show the server body or caught error.

- [ ] **Step 4: Run bridge, API, and syntax verification**

Run:

```bash
uv run pytest tests/test_cavalry_bridge.py tests/test_tessellation_api.py -q
node --check cavalry/plotter-bridge.js
```

Expected: all tests pass and syntax validation exits 0.

- [ ] **Step 5: Commit baking**

```bash
git add cavalry/plotter-bridge.js tests/test_cavalry_bridge.py
git commit -m "feat: bake Cavalry parameters into tessellations"
```

---

### Task 6: End-to-end discovery, cached-layer resilience, and final verification

**Files:**
- Modify: `tests/test_tessellation_api.py`
- Modify: `tests/test_frontend_contracts.py`
- Modify: `FEATURES.md`

**Interfaces:**
- Verifies custom patterns enter `/api/pfm/list`, expose the shared schema, generate paths, and leave cached layer SVG usable if their package disappears.

- [ ] **Step 1: Add integration tests for discovery and missing packages**

```python
def test_installed_pattern_is_discoverable_and_generates(client, complete_session):
    result = client.post(f"/api/tessellations/sessions/{complete_session}/finalize")
    pid = result.get_json()["pattern"]["id"]
    listed = client.get("/api/pfm/list").get_json()["pfms"]
    assert any(p["id"] == pid and p["family"] == "tessellation" for p in listed)
    schema = client.get(f"/api/pfm/{pid}/schema").get_json()
    assert any(p["name"] == "tone_response" for p in schema["params"])


def test_missing_package_does_not_remove_cached_layer_svg(client, installed_layer, library_root):
    cached = installed_layer.svg
    shutil.rmtree(library_root / installed_layer.source["pfm_id"])
    REGISTRY.pop(installed_layer.source["pfm_id"])
    response = client.post(
        f"/api/composition/layers/{installed_layer.id}/pathfinding/generate",
        json={"pfm_id": installed_layer.source["pfm_id"], "params": {}},
    )
    assert response.status_code == 400
    assert installed_layer.svg == cached
    assert installed_layer.pathfinding_style["status"] == "error"
    assert installed_layer.pathfinding_style["error"] == "Unknown PFM"
```

- [ ] **Step 2: Run integration tests and verify RED if resilience is missing**

Run: `uv run pytest tests/test_tessellation_api.py -q`

Expected: the cached SVG survives, but the assertion fails because the unknown-PFM branch has not yet recorded the layer error state.

- [ ] **Step 3: Preserve cached SVG on missing-pattern regeneration and document authoring**

In the regeneration endpoint's `if error:` branch, normalize the layer style,
set `status` to `"error"`, set `error` to the returned message, preserve
`layer.svg`, save composition layers, and include the composition payload in the
error response. Add to `FEATURES.md`:

```markdown
- **Cavalry tessellation authoring** — Select up to 16 numeric attributes, give each light/dark boundaries, choose a lattice preset or custom repeat vectors, and bake a reusable 32-state vector pattern into PlotterForge. All parameters share one editable PlotterForge tone-response curve.
```

Add a frontend contract assertion that `LayerStylePanel.svelte` retains
`tessellation: "Tessellation"` and that `PfmPicker.svelte` constructs preview
URLs from arbitrary PFM IDs, covering custom discovery without a special UI.

- [ ] **Step 4: Run complete automated verification**

Run:

```bash
uv run pytest tests -q
node --check cavalry/plotter-bridge.js
cd frontend && npm run check && npm run build
```

Expected: all Python tests pass, bridge syntax is valid, Svelte reports zero errors, and the production build succeeds.

- [ ] **Step 5: Perform the real-Cavalry smoke test when Cavalry is available**

Copy `cavalry/plotter-bridge.js` into Cavalry's Scripts folder. Verify:

1. one selected numeric attribute is added with its current value;
2. two bindings sweep together and both original values return after success;
3. Rectangular and Custom vector bakes appear in PlotterForge without restart;
4. a forced server stop during state upload restores both values and installs nothing;
5. rebaking the same name replaces the library entry but does not redraw an existing layer until Apply / Regenerate.

Expected: all five observations match, or the unavailable real-app check is reported explicitly rather than claimed.

- [ ] **Step 6: Commit integration coverage and docs**

```bash
git add tests/test_tessellation_api.py tests/test_frontend_contracts.py web/server.py FEATURES.md web/static/app
git commit -m "test: verify Cavalry tessellation authoring"
```
