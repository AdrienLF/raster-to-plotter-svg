# E2E Branch Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current 84-test Playwright suite deterministic and green, fix the project/event lifecycle defects it exposes, document the 13 deferred stories, and publish a ranked product roadmap.

**Architecture:** Keep the existing single-active-project Flask architecture, but forbid project transitions while a worker is active and clear cached/queued events during idle transitions. Boot the Svelte application before connecting SSE, reset transient state on project changes, and make E2E synchronization wait on observable API/DOM conditions rather than elapsed time.

**Tech Stack:** Python 3.13, Flask, unittest/pytest, Svelte 5, TypeScript, Playwright, PowerShell, Git.

---

## File map

- `web/server.py` — project-transition guard and transient event clearing.
- `tests/test_projects.py` — backend regressions for worker guards and event isolation.
- `frontend/src/App.svelte` — boot-before-stream lifecycle and boot error reporting.
- `frontend/src/lib/api.ts` — project-switch transient-state reset.
- `tests/test_frontend_contracts.py` — source contracts for frontend lifecycle ordering/reset.
- `frontend/e2e/fixtures.ts` — deterministic project, boot, composition, generation, and SVG helpers.
- `frontend/e2e/c-pathfinding.spec.ts` — layer editor accessible-name correction.
- `frontend/e2e/e-generator.spec.ts` — generation completion synchronization and E7.
- `frontend/e2e/f-composition.spec.ts` — layer action selectors and crop completion polling.
- `frontend/e2e/i-versions.spec.ts` — icon-button selectors by stable titles.
- `frontend/e2e/k-plot.spec.ts` — estimate response contract correction.
- `frontend/e2e/l-stream.spec.ts` — status badge scoping and terminal layer status correction.
- `frontend/e2e/m-journey.spec.ts` — namespaced SVG matching and generator completion synchronization.
- `frontend/e2e/plot-estimate.spec.ts` — plot estimate/job synchronization if the shared helper requires it.
- `frontend/e2e/README.md` — current suite layout and execution behavior.
- `frontend/e2e/USER_STORIES.md` — 73 implemented IDs and 13 deferred IDs.
- `docs/product-roadmap.md` — ranked quick wins, medium investments, and ambitious bets.

### Task 1: Guard project transitions and clear transient events

**Files:**
- Modify: `tests/test_projects.py`
- Modify: `web/server.py:122-166`
- Modify: `web/server.py:1584-1624`

- [ ] **Step 1: Add failing project lifecycle tests**

Extend `ProjectsApiTest.setUp()`/`tearDown()` to preserve worker and event globals, add `queue` to the imports, and add this test helper and three tests:

```python
class AliveThread:
    def is_alive(self):
        return True


class ProjectsApiTest(unittest.TestCase):
    def setUp(self):
        self._orig_dir = project_mod.PROJECTS_DIR
        self._orig_project = server._project
        self._orig_process_thread = server._process_thread
        self._orig_plot_thread = server._plot_thread
        self._orig_subscribers = server._subscribers
        self._orig_last_events = server._last_events
        self._tmp = tempfile.TemporaryDirectory()
        project_mod.PROJECTS_DIR = Path(self._tmp.name)
        server._project = project_mod.create_project("Start")
        server._process_thread = None
        server._plot_thread = None
        server._subscribers = set()
        server._last_events = {}
        self.client = server.app.test_client()

    def tearDown(self):
        project_mod.PROJECTS_DIR = self._orig_dir
        server._project = self._orig_project
        server._process_thread = self._orig_process_thread
        server._plot_thread = self._orig_plot_thread
        server._subscribers = self._orig_subscribers
        server._last_events = self._orig_last_events
        self._tmp.cleanup()

    def test_create_is_rejected_while_processing(self):
        current_id = server._project.id
        server._process_thread = AliveThread()

        response = self.client.post("/api/projects", json={"name": "Blocked"})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(server._project.id, current_id)

    def test_open_is_rejected_while_plotting(self):
        target = project_mod.create_project("Target")
        current_id = server._project.id
        server._plot_thread = AliveThread()

        response = self.client.post(f"/api/projects/{target.id}/open")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(server._project.id, current_id)

    def test_switch_clears_cached_and_queued_events(self):
        subscriber = server._subscribe_events()
        server.emit("proc", state="done", total=9)
        server.emit("state", state="done")

        response = self.client.post("/api/projects", json={"name": "Fresh"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(server._last_events, {})
        with self.assertRaises(queue.Empty):
            subscriber.get_nowait()
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_projects.py -q
```

Expected: the two active-worker tests receive 200 instead of 409, and cached/queued event assertions fail.

- [ ] **Step 3: Add the minimal server guard and event reset**

Add near `_switch_project()`:

```python
def _project_transition_blocked():
    process_active = bool(_process_thread and _process_thread.is_alive())
    plot_active = bool(_plot_thread and _plot_thread.is_alive())
    if process_active or plot_active:
        return jsonify(error="Cannot switch projects while an operation is active"), 409
    return None


def _switch_project(pid):
    global _project, _drawing, _current_svg, _placement
    _clear_events()
    _clear_last_proc_events()
    _clear_last_plot_events()
    _project = get_or_create(pid)
    _drawing = None
    _current_svg = None
    _placement = {"x": 0.0, "y": 0.0}
    _sync_current_svg_from_composition()
    return _project
```

Guard the three transition routes before mutation:

```python
@app.route("/api/projects", methods=["POST"])
def api_project_create():
    if blocked := _project_transition_blocked():
        return blocked
    name = (request.json or {}).get("name") or "Untitled"
    p = project_mod.create_project(name)
    _switch_project(p.id)
    return jsonify(ok=True, current=_project_public(_project), projects=project_mod.list_projects())


@app.route("/api/projects/<pid>/open", methods=["POST"])
def api_project_open(pid):
    if not (project_mod.PROJECTS_DIR / pid / "project.json").exists():
        return jsonify(error="Unknown project"), 404
    if blocked := _project_transition_blocked():
        return blocked
    _switch_project(pid)
    return jsonify(ok=True, current=_project_public(_project), projects=project_mod.list_projects())


@app.route("/api/projects/<pid>", methods=["DELETE"])
def api_project_delete(pid):
    if pid == _project.id:
        if blocked := _project_transition_blocked():
            return blocked
    project_mod.delete_project(pid)
    if pid == _project.id:
        remaining = project_mod.list_projects()
        _switch_project(remaining[0]["id"] if remaining else project_mod.create_project("Untitled").id)
    return jsonify(ok=True, current=_project_public(_project), projects=project_mod.list_projects())
```

- [ ] **Step 4: Run focused and full backend tests**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_projects.py tests/test_event_stream.py -q
uv run --with pytest python -m pytest -q
```

Expected: 9 focused project/event tests pass, then all 105 backend tests pass.

- [ ] **Step 5: Commit the backend lifecycle fix**

```powershell
git add tests/test_projects.py web/server.py
git commit -m "fix: isolate project transitions from active workers"
```

### Task 2: Boot before streaming and reset transient frontend state

**Files:**
- Modify: `tests/test_frontend_contracts.py`
- Modify: `frontend/src/App.svelte:1-32`
- Modify: `frontend/src/lib/api.ts:105-128`

- [ ] **Step 1: Add failing frontend lifecycle contracts**

Add these tests to `FrontendContractsTest`:

```python
def test_app_boots_before_connecting_event_stream(self):
    app = (ROOT / "frontend/src/App.svelte").read_text(encoding="utf-8")
    mount = re.search(r"onMount\(\(\) => \{(?P<body>.*?)\n  \}\);", app, re.DOTALL)

    self.assertIsNotNone(mount)
    body = mount.group("body")
    self.assertIn("api.boot()", body)
    self.assertIn(".then(() =>", body)
    self.assertLess(body.index("api.boot()"), body.index("connectStream()"))
    self.assertIn("pushLog(`Boot error:", body)

def test_project_switch_resets_transient_frontend_state(self):
    api_ts = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
    match = re.search(
        r"async switchProject\(payload: any\) \{(?P<body>.*?)\n  \},",
        api_ts,
        re.DOTALL,
    )

    self.assertIsNotNone(match)
    body = match.group("body")
    for assignment in (
        'studio.status = "Idle"',
        "studio.processing = false",
        "studio.plotting = false",
        "studio.progress = 0",
        "studio.stats = null",
        "studio.plotProgress = null",
        "studio.plotEstimate = null",
    ):
        self.assertIn(assignment, body)
```

- [ ] **Step 2: Run the contract tests and verify RED**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_frontend_contracts.py -q
```

Expected: both new lifecycle contracts fail against the current concurrent boot/stream code and incomplete reset.

- [ ] **Step 3: Sequence boot and stream connection in `App.svelte`**

Change the state import and `onMount` body to:

```svelte
import { pushLog, studio } from "./lib/state.svelte";

onMount(() => {
  let es: EventSource | null = null;
  void api
    .boot()
    .then(() => {
      es = connectStream();
    })
    .catch((error) => {
      studio.processing = false;
      studio.status = "Error";
      pushLog(`Boot error: ${error instanceof Error ? error.message : String(error)}`);
      console.error(error);
    });
  return () => es?.close();
});
```

- [ ] **Step 4: Reset transient state in `api.switchProject()`**

Replace the transient reset block with:

```typescript
this.applyProject(payload);
studio.previewSvg = null;
studio.stats = null;
studio.plotProgress = null;
studio.plotEstimate = null;
studio.processing = false;
studio.plotting = false;
studio.progress = 0;
studio.status = "Idle";
studio.step = "composition";
await this.boot();
```

- [ ] **Step 5: Verify contracts, type-check, and build**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_frontend_contracts.py -q
npm run check
npm run build
```

Expected: 15 frontend contract tests pass, Svelte reports 0 errors, and Vite exits 0. The known 14 accessibility warnings are allowed by the approved definition of done.

- [ ] **Step 6: Commit the frontend lifecycle fix**

```powershell
git add tests/test_frontend_contracts.py frontend/src/App.svelte frontend/src/lib/api.ts web/static/app
git commit -m "fix: initialize app before opening event stream"
```

### Task 3: Make shared Playwright helpers condition-based

**Files:**
- Modify: `frontend/e2e/fixtures.ts`
- Test: `frontend/e2e/l-stream.spec.ts`
- Test: `frontend/e2e/e-generator.spec.ts`
- Test: `frontend/e2e/f-composition.spec.ts`
- Test: `frontend/e2e/h-pens.spec.ts`

- [ ] **Step 1: Re-run the shared-race reproductions and verify RED**

Run:

```powershell
npx playwright test e2e/l-stream.spec.ts:25 e2e/e-generator.spec.ts:33 e2e/f-composition.spec.ts:22 e2e/f-composition.spec.ts:69 e2e/h-pens.spec.ts:22 --reporter=list
```

Expected: L2, E3, F1, F7, and H2 reproduce the startup/event/collection races or stale selectors.

- [ ] **Step 2: Replace project and boot helpers and add reusable polling**

In `frontend/e2e/fixtures.ts`, export a namespace-tolerant shape regex and add the following helpers:

```typescript
export const DRAWING_SHAPE = /<(?:[A-Za-z_][\w.-]*:)?(?:path|line|polyline|circle)(?=[\s/>])/;

export async function freshProject(request: APIRequestContext, baseURL: string, name: string) {
  await expect
    .poll(
      async () => {
        const response = await request.post(`${baseURL}/api/projects`, { data: { name } });
        if (response.status() === 409) return false;
        expect(response.ok(), "create project").toBeTruthy();
        return true;
      },
      { message: "wait for active worker before creating project", timeout: 30_000 },
    )
    .toBeTruthy();
}

export async function gotoApp(page: Page) {
  const bootComplete = page.waitForResponse(
    (response) =>
      response.url().includes("/api/versions") &&
      response.request().method() === "GET" &&
      response.ok(),
    { timeout: 20_000 },
  );
  await Promise.all([bootComplete, page.goto("/")]);
  await expect(page.locator(".status .badge")).not.toContainText("…", { timeout: 20_000 });
}

export async function getComposition(request: APIRequestContext, baseURL: string) {
  const response = await request.get(`${baseURL}/api/composition`);
  expect(response.ok(), "read composition").toBeTruthy();
  return (await response.json()).composition;
}

export async function waitForComposition(
  request: APIRequestContext,
  baseURL: string,
  predicate: (composition: any) => boolean,
  message: string,
  timeout = 20_000,
) {
  let latest: any;
  await expect
    .poll(
      async () => {
        latest = await getComposition(request, baseURL);
        return predicate(latest);
      },
      { message, timeout },
    )
    .toBeTruthy();
  return latest;
}

export async function waitForGeneratedLayer(
  request: APIRequestContext,
  baseURL: string,
  timeout = 60_000,
) {
  return waitForComposition(
    request,
    baseURL,
    (composition) => composition.layers.some((layer: any) => DRAWING_SHAPE.test(layer.svg ?? "")),
    "wait for generated layer geometry",
    timeout,
  );
}
```

Delete the old exact-placeholder `gotoApp()` implementation. Keep `waitForBoot()` only if another test imports it; otherwise remove it. Bound each initial boot attempt to 10 seconds and allow one reload only when the UI reports `Boot error: Failed to fetch` and Playwright observed a failed `/api/` request; HTTP boot errors must fail immediately with request diagnostics.

- [ ] **Step 3: Run L2 and H2 to verify the boot boundary is GREEN**

Run:

```powershell
npx playwright test e2e/l-stream.spec.ts:25 e2e/h-pens.spec.ts:22 --reporter=list
```

Expected: both tests pass; L2 reads the initialized backend and H2 starts from the true pen count.

### Task 4: Align selectors and assertions with current contracts

**Files:**
- Modify: `frontend/e2e/c-pathfinding.spec.ts`
- Modify: `frontend/e2e/f-composition.spec.ts`
- Modify: `frontend/e2e/i-versions.spec.ts`
- Modify: `frontend/e2e/k-plot.spec.ts`
- Modify: `frontend/e2e/l-stream.spec.ts`
- Modify: `frontend/e2e/m-journey.spec.ts`

- [ ] **Step 1: Verify each stale contract fails for the expected reason**

Run:

```powershell
npx playwright test e2e/c-pathfinding.spec.ts:110 e2e/i-versions.spec.ts:24 e2e/i-versions.spec.ts:41 e2e/k-plot.spec.ts:112 e2e/l-stream.spec.ts:61 e2e/m-journey.spec.ts:7 --reporter=list
```

Expected failures: layer editor waits for `Edit`; version rows wait for accessible names `Load`/`Down`; K9 reads undefined `total_shapes`; L3 rejects `clean`; M1 rejects `<ns0:path>`.

- [ ] **Step 2: Correct the layer action selectors**

In `openLayerEditor()`, retain the created layer name and click its current accessible name:

```typescript
const layer = add.composition.layers.at(-1);
const layerId: string = layer.id;
// ... generate and gotoApp ...
await page.getByRole("button", { name: `Open ${layer.name} path finding` }).click();
```

In F1, scope the stable title to the named layer row:

```typescript
await page.locator(".layer", { hasText: "Layer B" }).locator('button[title="Move down"]').click();
```

In F7, use the action titles within the current row:

```typescript
await page.locator(".layer").first().locator('button[title="Duplicate"]').click();
await expect(page.locator(".layer")).toHaveCount(before + 1, { timeout: 10_000 });
const copy = page.locator(".layer").filter({ hasText: "copy" }).first();
await copy.locator('button[title="Delete"]').click();
```

- [ ] **Step 3: Correct version icon selectors**

Replace role-name lookups inside version rows with title selectors:

```typescript
await page.locator(".ver", { hasText: "Restore Me" }).locator('button[title="Load"]').click();
await v2Row.locator('button[title="Down"]').click();
await v2Row.locator('button[title="Delete"]').click();
```

- [ ] **Step 4: Correct response/status/SVG contracts**

Apply these exact assertions:

```typescript
// k-plot.spec.ts K9
expect(est.paths, "estimate should report paths").toBeGreaterThan(0);

// l-stream.spec.ts L2
const badgeText = await page.locator(".status .badge").textContent();

// l-stream.spec.ts L3
expect(["clean", "error"].includes(layer?.pathfinding_style?.status), "layer should reach a terminal status").toBeTruthy();

// m-journey.spec.ts M1
expect(svg).toMatch(DRAWING_SHAPE);
```

Import `DRAWING_SHAPE` from `./fixtures` in `m-journey.spec.ts`.

- [ ] **Step 5: Run the corrected contract slice**

Run:

```powershell
npx playwright test e2e/c-pathfinding.spec.ts:110 e2e/c-pathfinding.spec.ts:128 e2e/c-pathfinding.spec.ts:205 e2e/f-composition.spec.ts:22 e2e/f-composition.spec.ts:69 e2e/i-versions.spec.ts:24 e2e/i-versions.spec.ts:41 e2e/k-plot.spec.ts:112 e2e/l-stream.spec.ts:25 e2e/l-stream.spec.ts:61 e2e/m-journey.spec.ts:7 --reporter=list
```

Expected: all 11 tests pass.

### Task 5: Synchronize generator, crop, version-save, and plot journeys

**Files:**
- Modify: `frontend/e2e/e-generator.spec.ts`
- Modify: `frontend/e2e/f-composition.spec.ts`
- Modify: `frontend/e2e/m-journey.spec.ts`
- Modify: `frontend/e2e/plot-estimate.spec.ts`
- Modify: `engine/versioning.py`
- Modify: `engine/project.py`
- Modify: `web/server.py`
- Modify: `frontend/src/lib/api.ts`
- Test: `tests/test_plot_job.py`
- Test: `tests/test_plot_estimate.py`
- Test: `tests/test_versions.py`
- Test: `tests/test_frontend_contracts.py`

- [ ] **Step 1: Verify asynchronous-flow failures are RED**

Run:

```powershell
npx playwright test e2e/e-generator.spec.ts e2e/f-composition.spec.ts:134 e2e/m-journey.spec.ts:65 e2e/m-journey.spec.ts:136 e2e/plot-estimate.spec.ts --reporter=list
```

Expected before corrections: generator journeys that wait for implicit output time out because opening Generate is intentionally manual-first, E3 does not exercise Auto on an existing generate layer, E5's in-place count assertion can pass before its click, F5 reads `crop: null` while the successful crop request is still running, and M2 waits for output it never starts. The plot journeys pass in isolation and are included here to verify that project/worker isolation also fixes their full-suite contamination.

- [ ] **Step 2: Start generation explicitly and wait for observable backend transitions**

Import `DRAWING_SHAPE`, `getComposition`, `waitForComposition`, and `waitForGeneratedLayer` in `e-generator.spec.ts`.

Opening Generate never creates a layer. For E2, E4, E5, and E6, click Generate before waiting for the initial backend output:

```typescript
await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
const initial = await waitForGeneratedLayer(request, baseURL!);
await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
```

E2 asserts that the explicit default generation contains `DRAWING_SHAPE`. E6 starts its timer before entering Generate, explicitly clicks Generate, and includes both backend generation and the resulting UI `Ready` state in its timing. E7 only checks panel grouping and must not wait for output because it does not start a worker.

For E3, explicitly create the first generate layer and capture its ID and SVG. With Auto checked, change `rot1_x` and poll until that same layer has the changed `source.params.rot1_x` and a different SVG. Wait for UI `Ready` before the next interaction. Then disable Auto, change `rot1_x` again, preserve the 600 ms debounce-negative window, and assert that the persisted SVG and source params are unchanged. Finally, click Generate and poll until the same layer reflects the pending param and changed SVG:

```typescript
await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
const initial = await waitForGeneratedLayer(request, baseURL!);
const layerId = initial.layers[0].id;
const initialSvg = initial.layers[0].svg;

await rot1xInput.fill("45");
await rot1xInput.press("Tab");
const autoRedrawn = await waitForComposition(
  request,
  baseURL!,
  (composition) => {
    const layer = composition.layers.find((candidate) => candidate.id === layerId);
    return layer?.source?.params?.rot1_x === 45 && layer.svg !== initialSvg;
  },
  "wait for debounced auto redraw",
  60_000,
);
const autoSvg = autoRedrawn.layers.find((layer) => layer.id === layerId)!.svg;

await autoCheck.uncheck();
await rot1xInput.fill("15");
await rot1xInput.press("Tab");
await page.waitForTimeout(600);
expect((await getComposition(request, baseURL!)).layers.find((layer) => layer.id === layerId)?.svg)
  .toBe(autoSvg);

await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
await waitForComposition(
  request,
  baseURL!,
  (composition) => {
    const layer = composition.layers.find((candidate) => candidate.id === layerId);
    return layer?.source?.params?.rot1_x === 15 && layer.svg !== autoSvg;
  },
  "wait for explicit redraw with Auto off",
  60_000,
);
```

For E4, explicitly generate the initial layer, wait for UI `Ready`, then poll each SVG transition. Wait for UI `Ready` after each backend transition before changing the next parameter:

```typescript
const svg1: string = initial.layers[0].svg;
expect(svg1).toMatch(DRAWING_SHAPE);

await rot1xInput.fill("45");
await rot1xInput.press("Tab");
const changed = await waitForComposition(
  request,
  baseURL!,
  (composition) => {
    const svg = composition.layers[0]?.svg ?? "";
    return svg.length > 0 && svg !== svg1;
  },
  "wait for rot1_x regeneration",
  60_000,
);
const svg2: string = changed.layers[0].svg;

await rot1xInput.fill("0");
await rot1xInput.press("Tab");
const reverted = await waitForComposition(
  request,
  baseURL!,
  (composition) => composition.layers[0]?.svg === svg1,
  "wait for deterministic regeneration",
  60_000,
);
expect(reverted.layers[0].svg).toBe(svg1);
```

For E5, explicitly generate the initial layer. After choosing `__new__`, wait until the backend selection is null before clicking Generate. Creating a new target completes only when the backend transitions from one layer to two; then wait for UI `Ready` before selecting the original target. For the in-place case, select the original ID and wait until the backend confirms that selection, disable Auto, capture its SVG and the stable set of two layer IDs, change `rot1_x`, and verify after 600 ms that no redraw occurred. Click Generate and poll until the same original ID has the new source param and changed SVG while both layer IDs remain stable:

```typescript
const first = await waitForComposition(
  request,
  baseURL!,
  (composition) => composition.layers.length === 1 && DRAWING_SHAPE.test(composition.layers[0]?.svg ?? ""),
  "wait for initial generator layer",
  60_000,
);
const firstLayerId: string = first.layers[0].id;
// After selecting __new__:
await waitForComposition(request, baseURL!, (composition) => composition.selected_layer_id === null, "wait for new-layer target selection", 10_000);
// After clicking Generate:
await waitForComposition(request, baseURL!, (composition) => composition.layers.length === 2, "wait for second generator layer", 60_000);
await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

// After selecting firstLayerId, disabling Auto, capturing originalSvg/stableLayerIds,
// changing rot1_x to 60, and proving the backend is still unchanged:
await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
await waitForComposition(
  request,
  baseURL!,
  (composition) => {
    const layer = composition.layers.find((candidate) => candidate.id === firstLayerId);
    const ids = composition.layers.map((candidate) => candidate.id).sort();
    return composition.layers.length === 2
      && ids.every((id, index) => id === stableLayerIds[index])
      && layer?.source?.params?.rot1_x === 60
      && layer.svg !== originalSvg;
  },
  "wait for observable in-place generator update",
  60_000,
);
```

- [ ] **Step 3: Poll crop completion**

Replace F5's fixed 300 ms delay and first composition read with:

```typescript
const composition = await waitForComposition(
  request,
  baseURL!,
  (value) => value.layers.find((layer: { id: string }) => layer.id === id)?.crop != null,
  "wait for crop-to-content",
  10_000,
);
const layer = composition.layers.find((value: { id: string }) => value.id === id);
expect(layer.crop).not.toBeNull();
```

After clicking Reset, poll until the same layer's crop is null.

- [ ] **Step 4: Synchronize M2 and plot metrics**

Use the exact accessible selector `getByRole("button", { name: "✦ Generate", exact: true })` for every generator action so the `▾Generate` panel-title button cannot also match. In M2, explicitly click that action, wait for `waitForGeneratedLayer(request, baseURL!)`, then wait for UI `Ready` so the SSE `done` event has populated stats. Save the version and capture its layer ID/SVG, mutate `rot1_x` until the same layer changes, then load the saved row by its `Load` title. Poll until the original ID/SVG is restored, assert the `rot1_x` control is hydrated back to the saved default `0`, assert UI `Ready`, and verify Save is disabled because snapshot load cleared stale stats before exporting. Hydrate generator ID/schema/params with Auto temporarily suppressed, then restore Auto behind a source-parameter equality guard so loading cannot enqueue a no-op redraw.

The focused M2 run exposed that generator output has no legacy `Drawing`, so version saving must persist the visible composition instead. Cover this with backend regressions: store a real PNG thumbnail plus an immutable `versions/<id>/composition.json` snapshot, keep only that relative path in `project.json`, restore and recompose the snapshot on load, and leave legacy drawing versions on their existing regenerate-on-load path. Validate a snapshot before mutating project/server state and return 409 for missing or corrupt data. Estimate and thumbnail parsing must explicitly ignore stale plot cancellation without clearing the shared stop event; plot execution must continue to honor cancellation, and a cancelled parse must never populate the resolved-path cache. Empty projects must still return 400. On frontend snapshot load, clear preview/stats/plot-derived state, settle at non-processing `Ready`, and skip legacy reprocessing.

In M3 and `plot-estimate.spec.ts`, install a listener for the UI's estimate response before navigating to Plot. Assert that response and its payload, then check the rendered metric. Do not issue a second estimate request from the test:

```typescript
const estimateResponsePromise = page.waitForResponse(
  (response) =>
    response.url().endsWith("/api/plot/estimate") &&
    response.request().method() === "GET",
  { timeout: 60_000 },
);
await gotoStep(page, "Plot");
const estimateResponse = await estimateResponsePromise;
const estimate = await estimateResponse.json();
expect(
  estimateResponse.ok(),
  `plot estimate response should succeed (${estimateResponse.status()}: ${estimate.error ?? "unknown error"})`,
).toBeTruthy();
expect(estimate.paths, "plot estimate should report paths").toBeGreaterThan(0);
await expect(pathCount).not.toHaveText("—", { timeout: 10_000 });
```

Keep the existing `Done` and fake-serial G-code assertions.

- [ ] **Step 5: Run the affected asynchronous flows**

Run:

```powershell
npx playwright test e2e/e-generator.spec.ts e2e/f-composition.spec.ts e2e/m-journey.spec.ts e2e/plot-estimate.spec.ts --reporter=list
```

Expected: all tests in the four files pass, including the E7 grouping test.

Also run `uv run python -m pytest tests/test_plot_job.py tests/test_plot_estimate.py tests/test_versions.py -q` and the focused M2 journey. Expected: estimates ignore a stale plot cancellation while plot execution still honors it, cancelled parses never populate the path cache, generator composition save/load tests pass, and M2 completes generate → version save → mutate → snapshot load → export.

- [ ] **Step 6: Commit the E2E stabilization**

```powershell
git add frontend/e2e tests/test_plot_job.py tests/test_plot_estimate.py web/server.py
git add docs/superpowers/plans/2026-06-27-e2e-branch-stabilization.md
git commit -m "fix: never cache cancelled plot parsing"
```

### Task 6: Correct E2E coverage documentation

**Files:**
- Modify: `frontend/e2e/README.md`
- Modify: `frontend/e2e/USER_STORIES.md`

- [ ] **Step 1: Replace the stale README layout claim**

Replace the stale README layout coverage claim with:

```markdown
The suite currently contains 17 spec files and 84 serial Chromium tests covering 73 of the 86 catalogued story IDs. Specs combine direct API setup with real UI interactions so expensive setup stays fast while user-visible behavior remains end-to-end.

Thirteen story IDs are intentionally deferred: A5, D1-D6, F6, F8-F10, H6, and K10. See `USER_STORIES.md` for their requirements.
```

- [ ] **Step 2: Replace the stale coverage section in `USER_STORIES.md`**

Use this coverage section:

```markdown
## Coverage status

The Playwright suite contains 84 tests covering 73 of the 86 story IDs above. Data-driven C7/C8 cases account for multiple tests under a single story ID.

### Deferred stories

- **A5:** Persistence across a backend restart, including composition, pens, and versions.
- **D1-D6:** SAM2 region creation, confinement, inversion, deletion, latency, and editing UX.
- **F6:** Composition masks.
- **F8:** Alignment toolbar behavior.
- **F9:** On-canvas snapping.
- **F10:** Handle-versus-input UX benchmark.
- **H6:** Many-pen readability inventory.
- **K10:** Plot-panel action hierarchy inventory.

These are backlog items, not implied coverage. A story moves out of this list only when its named Playwright test runs in the complete suite.
```

- [ ] **Step 3: Verify the documented counts mechanically**

Run:

```powershell
$stories = (Select-String -Path 'frontend\e2e\USER_STORIES.md' -Pattern '(?m)^\- \*\*([A-M][0-9]+) \[' -AllMatches -CaseSensitive).Matches | ForEach-Object { $_.Groups[1].Value }
Push-Location frontend
try { $listed = npx playwright test --list } finally { Pop-Location }
$covered = $listed | ForEach-Object { if ($_ -match '^\s+\[chromium\].* ›\s*((?:[A-M][0-9]+)(?:\+[A-M][0-9]+)*)\s*:') { $Matches[1] -split '\+' } } | Where-Object { $_ -in $stories } | Sort-Object -Unique
$deferred = $stories | Where-Object { $_ -notin $covered }
($listed | Select-String '^Total:').Line
"stories=$($stories.Count) covered=$($covered.Count) deferred=$($deferred.Count)"
"deferred=$($deferred -join ', ')"
```

Expected: `Total: 84 tests in 17 files`, `stories=86 covered=73 deferred=13`, and deferred IDs `A5, D1-D6, F6, F8-F10, H6, K10`.

- [ ] **Step 4: Commit coverage documentation**

```powershell
git add frontend/e2e/README.md frontend/e2e/USER_STORIES.md docs/superpowers/plans/2026-06-27-e2e-branch-stabilization.md
git commit -m "docs: record current e2e coverage and backlog"
```

### Task 7: Verify the branch twice

**Files:**
- Inspect: all modified files
- Inspect: `frontend/e2e/perf/playwright-report.json`
- Inspect: Git working tree

- [ ] **Step 1: Run backend and frontend gates**

```powershell
uv run --with pytest python -m pytest
Set-Location frontend
npm run check
npm run build
Set-Location ..
```

Expected: 105 backend tests pass; Svelte reports 0 errors; Vite exits 0.

- [ ] **Step 2: Run the complete Playwright suite**

```powershell
Set-Location frontend
npm run e2e
Set-Location ..
```

Expected: `84 passed`, `0 failed`, `0 flaky`, `0 skipped`.

- [ ] **Step 3: Repeat the complete Playwright suite**

Run the same `npm run e2e` command again.

Expected: a second independent `84 passed` result. Any intermittent failure blocks completion and returns to the failing spec's condition boundary.

- [ ] **Step 4: Inspect generated artifacts and repository state**

```powershell
git diff --check
git status --short
git diff --stat
git hash-object web/static/app/assets/index-C-dsL8rm.css
git rev-parse HEAD:web/static/app/assets/index-C-dsL8rm.css
```

Expected: no whitespace errors; only intentional source/docs/build changes remain; the CSS hashes match if Git reports only a timestamp/line-ending marker.

- [ ] **Step 5: Commit an intentional rebuilt frontend if needed**

If `npm run build` changes tracked `web/static/app` content hashes, stage those exact files with their frontend source change and commit:

```powershell
git add web/static/app
git commit -m "build: refresh frontend bundle"
```

If hashes already match `HEAD`, refresh the index metadata without changing content:

```powershell
git update-index --refresh
```

### Task 8: Audit the finished product and publish the roadmap

**Files:**
- Create: `docs/product-roadmap.md`
- Inspect: `README.md`
- Inspect: `frontend/src/components/**/*.svelte`
- Inspect: `frontend/src/lib/api.ts`
- Inspect: `web/server.py`
- Inspect: `engine/**/*.py`
- Inspect: `frontend/e2e/USER_STORIES.md`
- Inspect: `frontend/e2e/perf/results.jsonl`

- [ ] **Step 1: Audit the verified product across four lenses**

Record evidence for:

```markdown
1. Workflow and discoverability: first artwork, editing loops, terminology, empty/error states.
2. Reliability and hardware safety: cancellation, recovery, project/worker ownership, preflight, plot resumption.
3. Creative power and output quality: regions, masks, generators, reusable recipes, pen assignment, plot preview.
4. Engineering leverage: test duration, performance observability, module boundaries, durable jobs, extension points.
```

- [ ] **Step 2: Write the roadmap with this exact decision structure**

Create `docs/product-roadmap.md` with:

```markdown
# Plotter Studio Product Roadmap

## Product assessment
## What is already strong
## Friction and risks observed
## Prioritization method
## Quick wins (days)
## Medium investments (weeks)
## Ambitious bets (months)
## Recommended sequence
## Explicit non-priorities
```

Score each recommendation from 1-5 for user impact, confidence, and effort. Rank by `(impact × confidence) / effort`, then adjust only for hardware safety or prerequisite ordering. Every recommendation must include the user problem, proposed outcome, evidence, dependencies, and principal risk.

At minimum, evaluate these concrete candidates rather than assuming they all belong on the roadmap:

- guided first-artwork flow and contextual empty states;
- removal of current form-label accessibility warnings;
- clear autosave/dirty/error/recovery indicators;
- plot preflight with page bounds, pen order, travel preview, and hardware checklist;
- operation cancellation and project-safe background jobs;
- reusable generator/PFM/pen recipes;
- completed region, mask, alignment, and snapping workflows;
- visual before/after and version comparison;
- performance budgets surfaced as trends rather than log lines;
- project-scoped durable worker architecture;
- camera-assisted paper alignment and calibration;
- PFM/generator plugin SDK.

- [ ] **Step 3: Self-review the roadmap**

Run:

```powershell
Get-Content -Raw -LiteralPath 'docs\product-roadmap.md'
git diff --check -- docs/product-roadmap.md
```

Expected: every named section contains concrete prose and no whitespace errors are reported. Confirm that ambitious items do not outrank safety/reliability prerequisites without an explicit reason.

- [ ] **Step 4: Commit the roadmap**

```powershell
git add docs/product-roadmap.md
git commit -m "docs: rank the next Plotter Studio improvements"
```

### Task 9: Final completion check

**Files:**
- Inspect: Git history and working tree
- Inspect: latest backend/frontend/E2E outputs

- [ ] **Step 1: Confirm branch history and cleanliness**

```powershell
git status --short --branch
git log --oneline --decorate -8
git diff main...HEAD --stat
```

Expected: the intended stabilization, documentation, and roadmap commits are present; no accidental uncommitted changes remain.

- [ ] **Step 2: Report verified completion evidence**

Report the exact backend test count, frontend check/build result, both Playwright run counts and durations, deferred story IDs, commits created, and the top roadmap recommendations. Do not push or open a pull request unless the user separately requests it.
