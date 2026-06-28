import { readFileSync } from "fs";
import { join } from "path";
import {
  test,
  expect,
  ASSETS,
  DRAWING_SHAPE,
  freshProject,
  getComposition,
  gotoApp,
  importImage,
  runPathFinding,
  gotoStep,
  waitForGeneratedLayer,
  waitForComposition,
  waitForReady,
} from "./fixtures";

// M1 [R+P]: Import → 2 PF layers (different algorithms) → load pens → export SVG.
// Skips the SAM2 region step (D-epic, gated on model availability).
test("M1: multi-layer artwork — import, 2 PF layers, pens, export SVG", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E M1");

  // Upload image and add two layers with different PFMs via API (fast path).
  await request.post(`${baseURL}/api/image`, {
    multipart: {
      file: { name: "sample.png", mimeType: "image/png", buffer: readFileSync(join(ASSETS, "sample.png")) },
    },
  });
  const addA = await (await request.post(`${baseURL}/api/composition/add-layer`, { data: { name: "Spiral" } })).json();
  const idA: string = addA.composition.layers.at(-1).id;
  await request.post(`${baseURL}/api/composition/layers/${idA}/pathfinding/generate`, {
    data: { pfm_id: "spiral", params: {} },
  });

  const addB = await (await request.post(`${baseURL}/api/composition/add-layer`, { data: { name: "Stipple" } })).json();
  const idB: string = addB.composition.layers.at(-1).id;
  await request.post(`${baseURL}/api/composition/layers/${idB}/pathfinding/generate`, {
    data: { pfm_id: "voronoi_stippling", params: { n_points: 20 } },
  });

  await gotoApp(page);

  // Both layers visible in the Composition panel.
  await expect(page.locator(".layer")).toHaveCount(2, { timeout: 10_000 });

  // Load a pen library via UI.
  const { libraries } = await (await request.get(`${baseURL}/api/pens`)).json();
  await page.locator('select[title="Load a pen library"]').selectOption(libraries[0]);
  await expect(page.locator(".pen")).toHaveCount(
    (await (await request.get(`${baseURL}/api/pens/library/${encodeURIComponent(libraries[0])}`)).json()).pens.length,
    { timeout: 10_000 },
  );

  // Export SVG via API — should include geometry from both layers.
  const r = await request.get(`${baseURL}/api/export`);
  expect(r.ok()).toBeTruthy();
  const svg = await r.text();
  expect(svg).toMatch(/^<svg\s/);
  // Combined export must contain at least one drawn shape from the layers.
  expect(svg).toMatch(DRAWING_SHAPE);
});

// M2 [R]: Generator-only artwork — generate → save version → export SVG.
test("M2: generator-only artwork — generate, version, export", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E M2");
  await gotoApp(page);

  // Jump to Generate and explicitly run the default spokes_and_circles generator.
  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });
  await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
  await waitForGeneratedLayer(request, baseURL!);
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

  // Versions panel is collapsed by default in the Generate step — open it.
  await page.getByRole("button", { name: "Versions" }).click();

  // Save a named version (＋ Save is enabled once studio.stats is set by the done event).
  await page.locator('input[placeholder="Version name…"]').fill("M2 snapshot");
  const saveVersion = page.getByRole("button", { name: "＋ Save" });
  await expect(saveVersion).toBeEnabled();
  await saveVersion.click();
  const versionRow = page.locator(".ver", { hasText: "M2 snapshot" });
  await expect(versionRow.locator(".name")).toBeVisible({ timeout: 10_000 });
  const savedComposition = await getComposition(request, baseURL!);
  const savedLayerId = savedComposition.layers[0].id;
  const savedSvg = savedComposition.layers[0].svg;

  // Mutate the generated layer so loading the snapshot has an observable boundary.
  const rot1xInput = page.locator('.ctrl:has(label[for="rot1_x"]) input.numbox');
  await rot1xInput.fill("45");
  await rot1xInput.press("Tab");
  await waitForComposition(
    request,
    baseURL!,
    (composition) => {
      const layer = composition.layers.find((candidate) => candidate.id === savedLayerId);
      return layer?.source?.params?.rot1_x === 45 && layer.svg !== savedSvg;
    },
    "wait for generator mutation before version load",
    60_000,
  );
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

  await versionRow.locator('button[title="Load"]').click();
  await waitForComposition(
    request,
    baseURL!,
    (composition) => {
      const layer = composition.layers.find((candidate) => candidate.id === savedLayerId);
      return composition.layers.length === 1 && layer?.svg === savedSvg;
    },
    "wait for generator composition snapshot restore",
    60_000,
  );
  await expect
    .poll(
      async () => Number(await rot1xInput.inputValue()),
      { message: "wait for restored generator controls", timeout: 10_000 },
    )
    .toBe(0);
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
  await expect(saveVersion).toBeDisabled();

  // Export — the restored generated SVG should be a valid document.
  const r = await request.get(`${baseURL}/api/export`);
  expect(r.ok(), "export should succeed").toBeTruthy();
  const svg = await r.text();
  expect(svg).toMatch(/^<svg\s/);
  expect(svg).toContain("</svg>");
});

// M3 [R+P]: Photo → plot dry-run — full UI journey: import → PFM → estimate → plot → done.
// Tests the end-to-end "real user" flow against the fake serial (PLOTTER_FAKE_SERIAL=1).
test("M3: photo → plot dry-run — import, path finding, estimate, plot to completion", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E M3");
  await gotoApp(page);

  // Import image via UI.
  await importImage(page, join(ASSETS, "sample.png"));

  // Run path finding via UI — waits for SSE "Ready".
  await runPathFinding(page);

  // Navigate to Plot step and observe its own estimate request.
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
  const pathCount = page.locator(".metrics div", { hasText: "Paths" }).locator("strong");
  await expect(pathCount).not.toHaveText("—", { timeout: 10_000 });

  // Clear serial log, start the plot, and wait for the fake plotter to finish.
  await request.delete(`${baseURL}/api/_test/serial-log`);
  await page.getByRole("button", { name: "Start", exact: true }).click();
  await expect(page.locator(".status .state")).toHaveText("Done", { timeout: 60_000 });

  // The fake serial received real G-code — confirms the plotter path ran end-to-end.
  const log = await (await request.get(`${baseURL}/api/_test/serial-log`)).json();
  expect(log.writes.some((c: string) => c.startsWith("G00") || c.startsWith("G01"))).toBeTruthy();
});

// M4 [U]: new-user happy path — blank app → import image → path finding → Export SVG enabled.
// Records the number of UI interactions as a UX baseline. Goal: ≤ 5 steps.
test("M4: new-user happy path — import → run → export reachable in ≤ 5 steps", async ({ page, request, baseURL, recordPerf }) => {
  await freshProject(request, baseURL!, "E2E M4");
  await gotoApp(page);

  let steps = 0;

  // Step 1: import image via the hidden file input.
  await importImage(page, join(ASSETS, "sample.png"));
  steps++;

  // Step 2: run path finding.
  await page.locator('button[title="Run path finding"]').click();
  steps++;
  await waitForReady(page);

  // Steps 3 + 4: open File menu → verify Export SVG is enabled.
  await page.getByRole("button", { name: "File" }).click();
  steps++;
  await expect(page.getByRole("button", { name: "Export SVG" })).toBeEnabled();
  await page.keyboard.press("Escape");

  recordPerf({ story: "M4", duration_ms: steps }); // duration_ms carries step count
  console.log(`[perf] M4: new-user happy path in ${steps} steps`);
  expect(steps, "first export reachable within 5 UI steps").toBeLessThanOrEqual(5);
});
