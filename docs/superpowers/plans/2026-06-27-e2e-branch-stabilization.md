# E2E Branch Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current 82-test Playwright suite deterministic and green, fix the project/event lifecycle defects it exposes, document the 12 deferred stories, and publish a ranked product roadmap.

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
- `frontend/e2e/USER_STORIES.md` — 74 implemented IDs and 12 deferred IDs.
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

Expected: 9 focused project/event tests pass, then all 83 backend tests pass (80 existing plus 3 new).

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
export const DRAWING_SHAPE = /<(?:[A-Za-z_][\w.-]*:)?(?:path|line|polyline|circle)\b/;

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

Delete the old exact-placeholder `gotoApp()` implementation. Keep `waitForBoot()` only if another test imports it; otherwise remove it.

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
- Modify: `frontend/e2e/fixtures.ts`

- [ ] **Step 1: Verify asynchronous-flow failures are RED**

Run:

```powershell
npx playwright test e2e/e-generator.spec.ts e2e/f-composition.spec.ts:133 e2e/m-journey.spec.ts:51 e2e/m-journey.spec.ts:78 e2e/plot-estimate.spec.ts --reporter=list
```

Expected before corrections: E3-E5, F5, and M2 fail. F5 specifically reads `crop: null` while the successful crop request is still running. The plot journeys pass in isolation and are included here to verify that project/worker isolation also fixes their full-suite contamination.

- [ ] **Step 2: Wait for real generator output instead of a possibly stale `Ready` label**

Import `DRAWING_SHAPE`, `getComposition`, `waitForComposition`, and `waitForGeneratedLayer` in `e-generator.spec.ts`.

For E2/E4/E5/E6, replace the initial `Ready` wait with:

```typescript
const initial = await waitForGeneratedLayer(request, baseURL!);
```

At the end of E7, call `await waitForGeneratedLayer(request, baseURL!)` so the auto-generation worker cannot leak into E5.

For E3, preserve the debounce-negative assertion and verify the backend remains empty before explicit generation:

```typescript
await page.waitForTimeout(600);
expect((await getComposition(request, baseURL!)).layers).toHaveLength(0);
await page.getByRole("button", { name: "Generate" }).click();
await waitForGeneratedLayer(request, baseURL!);
```

For E4, poll each SVG transition:

```typescript
const svg1: string = initial.layers[0].svg;
expect(svg1).toMatch(DRAWING_SHAPE);

await rot1xInput.fill("45");
await rot1xInput.press("Tab");
const changed = await waitForComposition(
  request,
  baseURL!,
  (composition) => composition.layers[0]?.svg && composition.layers[0].svg !== svg1,
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

For E5, poll layer counts in the backend after each generate instead of sleeping or reading the DOM immediately:

```typescript
const first = await waitForComposition(
  request,
  baseURL!,
  (composition) => composition.layers.length === 1 && DRAWING_SHAPE.test(composition.layers[0]?.svg ?? ""),
  "wait for initial generator layer",
  60_000,
);
const firstLayerId: string = first.layers[0].id;
// After selecting __new__ and clicking Generate:
await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
await waitForComposition(request, baseURL!, (composition) => composition.layers.length === 2, "wait for second generator layer", 60_000);
// After selecting firstLayerId and clicking Generate:
await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
await waitForComposition(request, baseURL!, (composition) => composition.layers.length === 2, "wait for in-place generator update", 60_000);
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

In M2, replace the status-only wait with `await waitForGeneratedLayer(request, baseURL!)`, then assert the Save button is enabled before clicking it.

In M3 and `plot-estimate.spec.ts`, wait for the estimate API and UI metric together:

```typescript
await expect
  .poll(async () => {
    const response = await request.get(`${baseURL}/api/plot/estimate`);
    if (!response.ok()) return 0;
    return (await response.json()).paths ?? 0;
  }, { message: "wait for plot estimate", timeout: 30_000 })
  .toBeGreaterThan(0);
await expect(pathCount).not.toHaveText("—", { timeout: 10_000 });
```

Keep the existing `Done` and fake-serial G-code assertions.

- [ ] **Step 5: Run the affected asynchronous flows**

Run:

```powershell
npx playwright test e2e/e-generator.spec.ts e2e/f-composition.spec.ts e2e/m-journey.spec.ts e2e/plot-estimate.spec.ts --reporter=list
```

Expected: all tests in the four files pass, including the uncommitted E7 test.

- [ ] **Step 6: Commit the E2E stabilization**

```powershell
git add frontend/e2e
git commit -m "test: stabilize Playwright journeys and contracts"
```

### Task 6: Correct E2E coverage documentation

**Files:**
- Modify: `frontend/e2e/README.md`
- Modify: `frontend/e2e/USER_STORIES.md`

- [ ] **Step 1: Replace the stale README layout claim**

Replace the statement that only three representative specs ship with:

```markdown
The suite currently contains 16 spec files and 82 serial Chromium tests covering 74 of the 86 catalogued story IDs. Specs combine direct API setup with real UI interactions so expensive setup stays fast while user-visible behavior remains end-to-end.

Twelve story IDs are intentionally deferred: D1-D6, F6, F8-F10, H6, and K10. See `USER_STORIES.md` for their requirements.
```

- [ ] **Step 2: Replace `Implemented now (representative specs)` in `USER_STORIES.md`**

Use this coverage section:

```markdown
## Coverage status

The Playwright suite contains 82 tests covering 74 of the 86 story IDs above. Data-driven C7/C8 cases account for multiple tests under a single story ID.

### Deferred stories

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
$stories = (Select-String -Path 'frontend\e2e\USER_STORIES.md' -Pattern '(?m)^\- \*\*([A-M][0-9]+)' -AllMatches -CaseSensitive).Matches | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
$tests = (Select-String -Path 'frontend\e2e\*.spec.ts' -Pattern '\b([A-M][0-9]+)\b' -AllMatches -CaseSensitive).Matches | ForEach-Object { $_.Groups[1].Value } | Where-Object { $_ -notin @('G00', 'G01') } | Sort-Object -Unique
"stories=$($stories.Count) covered=$($tests.Count) deferred=$($stories.Count - $tests.Count)"
```

Expected: `stories=86 covered=74 deferred=12`.

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

Expected: 83 backend tests pass; Svelte reports 0 errors; Vite exits 0.

- [ ] **Step 2: Run the complete Playwright suite**

```powershell
Set-Location frontend
npm run e2e
Set-Location ..
```

Expected: `82 passed`, `0 failed`, `0 flaky`, `0 skipped`.

- [ ] **Step 3: Repeat the complete Playwright suite**

Run the same `npm run e2e` command again.

Expected: a second independent `82 passed` result. Any intermittent failure blocks completion and returns to the failing spec's condition boundary.

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
