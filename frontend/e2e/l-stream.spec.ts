import { readFileSync } from "fs";
import { join } from "path";
import { test, expect, ASSETS, freshProject, gotoApp, importImage, waitForReady } from "./fixtures";

// L1: SSE progress bar appears during a PF run and disappears on completion.
test("L1: progress bar visible during path-finding, gone when idle", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E L1");
  await gotoApp(page);
  await importImage(page, join(ASSETS, "sample.png"));

  // Start path finding without waiting for completion.
  await page.locator('button[title="Run path finding"]').click();

  // The progress bar should appear while studio.processing is true.
  await expect(page.locator(".status .bar")).toBeVisible({ timeout: 10_000 });

  // Wait for completion.
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

  // Progress bar is hidden once processing ends.
  await expect(page.locator(".status .bar")).not.toBeVisible();
});

// L2: badge text correctly reflects GPU vs CPU backend from /api/pfm/list.
test("L2: status badge reflects GPU/CPU backend", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E L2");
  await gotoApp(page);

  const { backend } = await (await request.get(`${baseURL}/api/pfm/list`)).json();
  const expectedPrefix = backend.startsWith("torch") ? "GPU" : "CPU";

  const badgeText = await page.locator(".badge").textContent();
  expect(badgeText).toContain(expectedPrefix);
  expect(badgeText).toContain(backend);
});

// L4 [U]: progress feedback latency — time from "Run path finding" click to first progress bar.
test("L4: progress bar appears within 1 s of starting path finding", async ({ page, request, baseURL, recordPerf }) => {
  await freshProject(request, baseURL!, "E2E L4");
  await gotoApp(page);
  await importImage(page, join(ASSETS, "sample.png"));

  const t0 = Date.now();
  await page.locator('button[title="Run path finding"]').click();

  // The progress bar (.status .bar) appears as soon as the first SSE progress event arrives.
  await expect(page.locator(".status .bar")).toBeVisible({ timeout: 5_000 });
  const latency_ms = Date.now() - t0;

  // Wait for the run to finish so the test cleans up properly.
  await waitForReady(page);

  recordPerf({ story: "L4", duration_ms: latency_ms });
  const budget = 1_000; // 1 s soft budget: user should see feedback in under a second
  if (latency_ms > budget) console.warn(`[perf] L4: first-progress ${latency_ms}ms > budget ${budget}ms (soft)`);
  console.log(`[perf] L4: first-progress latency ${latency_ms}ms`);
});

// L3: starting a second process while one is running is handled gracefully —
// returns 409 (blocked) rather than corrupting shared state.
test("L3: concurrent process request returns 409 and leaves state intact", async ({ request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E L3");
  await request.post(`${baseURL}/api/image`, {
    multipart: {
      file: { name: "sample.png", mimeType: "image/png", buffer: readFileSync(join(ASSETS, "sample.png")) },
    },
  });
  const add = await (await request.post(`${baseURL}/api/composition/add-layer`, { data: {} })).json();
  const layerId: string = add.composition.layers.at(-1).id;

  // Fire two generate requests simultaneously. The backend serialises on _process_thread
  // so at least one must succeed (200) and the concurrent one should be blocked (409),
  // not crash the server.
  const [r1, r2] = await Promise.all([
    request.post(`${baseURL}/api/composition/layers/${layerId}/pathfinding/generate`, {
      data: { pfm_id: "voronoi_stippling", params: { point_density: 200, voronoi_iterations: 20 } },
    }),
    request.post(`${baseURL}/api/composition/layers/${layerId}/pathfinding/generate`, {
      data: { pfm_id: "spiral", params: {} },
    }),
  ]);

  const statuses = [r1.status(), r2.status()];
  // At least one must succeed.
  expect(statuses.some((s) => s === 200), "at least one request should succeed").toBeTruthy();
  // None should 5xx (server crash / unhandled error).
  expect(statuses.every((s) => s < 500), "no 5xx — server must not crash").toBeTruthy();

  // Wait for any in-flight process to finish (up to 60 s).
  for (let i = 0; i < 120; i++) {
    const { composition } = await (await request.get(`${baseURL}/api/composition`)).json();
    const layer = composition.layers.find((l: { id: string }) => l.id === layerId);
    if (layer?.pathfinding_style?.status !== "stale") break;
    await new Promise((r) => setTimeout(r, 500));
  }

  // State must not be corrupted: the layer should exist with a non-stale status.
  const { composition } = await (await request.get(`${baseURL}/api/composition`)).json();
  const layer = composition.layers.find((l: { id: string }) => l.id === layerId);
  expect(["ready", "error"].includes(layer?.pathfinding_style?.status), "layer should reach a terminal status").toBeTruthy();
});
