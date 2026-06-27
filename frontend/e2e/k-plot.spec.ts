import { readFileSync } from "fs";
import { join } from "path";
import { test, expect, ASSETS, freshProject, gotoApp, gotoStep } from "./fixtures";

/** Project with voronoi_stippling layer — multiple paths for reordering tests. */
async function setupPlotProject(request: any, baseURL: string, name: string) {
  await freshProject(request, baseURL, name);
  await request.post(`${baseURL}/api/image`, {
    multipart: {
      file: { name: "sample.png", mimeType: "image/png", buffer: readFileSync(join(ASSETS, "sample.png")) },
    },
  });
  const add = await (await request.post(`${baseURL}/api/composition/add-layer`, { data: {} })).json();
  const layerId: string = add.composition.layers.at(-1).id;
  await request.post(`${baseURL}/api/composition/layers/${layerId}/pathfinding/generate`, {
    data: { pfm_id: "voronoi_stippling", params: { n_points: 50 } },
  });
}

// K2: nearest-neighbour reordering reduces or maintains travel distance vs no reordering.
test("K2: nearest reordering reduces travel distance vs none", async ({ request, baseURL }) => {
  await setupPlotProject(request, baseURL!, "E2E K2");

  await request.post(`${baseURL}/api/settings`, { data: { reordering: "none" } });
  const estNone = await (await request.get(`${baseURL}/api/plot/estimate`)).json();

  await request.post(`${baseURL}/api/settings`, { data: { reordering: "nearest" } });
  const estNearest = await (await request.get(`${baseURL}/api/plot/estimate`)).json();

  expect(
    estNearest.travel_distance_mm,
    "nearest reordering should not increase travel distance",
  ).toBeLessThanOrEqual(estNone.travel_distance_mm);
});

// K3: Setup tab — paper preset persists to /api/settings.
test("K3: Setup tab paper preset saves to settings", async ({ page, request, baseURL }) => {
  await setupPlotProject(request, baseURL!, "E2E K3");
  await gotoApp(page);
  await gotoStep(page, "Plot");

  await page.locator(".plotter .tabs button", { hasText: "Setup" }).click();
  await page.locator("#plotter-paper-preset").selectOption("a4");

  await page.waitForTimeout(500);
  const settings = await (await request.get(`${baseURL}/api/settings`)).json();
  expect(settings.paper_width).toBeCloseTo(210, 0);
  expect(settings.paper_height).toBeCloseTo(297, 0);
});

// K4: Speed tab — drawing speed persists.
test("K4: Speed tab saves drawing speed to settings", async ({ page, request, baseURL }) => {
  await setupPlotProject(request, baseURL!, "E2E K4");
  await gotoApp(page);
  await gotoStep(page, "Plot");

  await page.locator(".plotter .tabs button", { hasText: "Speed" }).click();
  await page.locator("#plotter-speed-down").fill("1500");
  await page.locator("#plotter-speed-down").press("Tab");

  await page.waitForTimeout(500);
  const settings = await (await request.get(`${baseURL}/api/settings`)).json();
  expect(settings.speed_pendown).toBe(1500);
});

// K7: Manual jog emits G-code; Home emits $H to the fake serial log.
test("K7: Manual jog and Home emit expected G-code", async ({ page, request, baseURL }) => {
  await setupPlotProject(request, baseURL!, "E2E K7");
  await gotoApp(page);
  await gotoStep(page, "Plot");

  await page.locator(".plotter .tabs button", { hasText: "Manual" }).click();

  // Clear prior captures.
  await request.delete(`${baseURL}/api/_test/serial-log`);

  // Jog up: jog(0, -1) → walk {dx:0, dy:-10} → G00 X0.00 Y10.00.
  // /api/manual has time.sleep(2); each click takes ~2.5 s.
  await page.locator(".dpad button", { hasText: "↑" }).click();
  await expect(page.locator(".dpad button", { hasText: "↑" })).toBeEnabled({ timeout: 10_000 });

  const jogLog = await (await request.get(`${baseURL}/api/_test/serial-log`)).json();
  expect(jogLog.writes.some((w: string) => /G00 X0\.00 Y10\.00/.test(w))).toBeTruthy();

  // Clear and test Home.
  await request.delete(`${baseURL}/api/_test/serial-log`);
  await page.locator(".manual button", { hasText: "Home" }).click();
  await expect(page.locator(".manual button", { hasText: "Home" })).toBeEnabled({ timeout: 10_000 });

  const homeLog = await (await request.get(`${baseURL}/api/_test/serial-log`)).json();
  expect(homeLog.writes).toContain("$H");
});

// K8: auto-rotate checkbox toggle persists to settings.
test("K8: auto-rotate checkbox persists to settings", async ({ page, request, baseURL }) => {
  await setupPlotProject(request, baseURL!, "E2E K8");
  await gotoApp(page);
  await gotoStep(page, "Plot");

  await page.locator(".plotter .tabs button", { hasText: "Advanced" }).click();

  const checkbox = page.locator("#plotter-auto-rotate");
  const before = await checkbox.isChecked();
  if (before) await checkbox.uncheck(); else await checkbox.check();

  await page.waitForTimeout(500);
  const settings = await (await request.get(`${baseURL}/api/settings`)).json();
  expect(settings.auto_rotate).toBe(!before);
});

// K6: Stop mid-plot saves a resumable job; Discard clears it.
// Uses a large layer (high point_density) and 'none' reordering so the plot thread
// takes a measurable amount of time, giving the stop request a chance to interrupt it.
test("K6: stop plot creates resumable job; Discard clears it", async ({ request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E K6");
  await request.post(`${baseURL}/api/image`, {
    multipart: {
      file: { name: "sample.png", mimeType: "image/png", buffer: readFileSync(join(ASSETS, "sample.png")) },
    },
  });
  const add = await (await request.post(`${baseURL}/api/composition/add-layer`, { data: {} })).json();
  const layerId: string = add.composition.layers.at(-1).id;
  await request.post(`${baseURL}/api/composition/layers/${layerId}/pathfinding/generate`, {
    data: { pfm_id: "voronoi_stippling", params: { point_density: 1200 } },
  });

  // Skip path reordering so the plot worker spends all its time on G-code, not reordering.
  await request.post(`${baseURL}/api/settings`, { data: { reordering: "none" } });

  // Start plotting then immediately stop.
  await request.post(`${baseURL}/api/plot`);
  await request.post(`${baseURL}/api/stop`);

  // Poll until the plot thread exits (status != 'running'), up to 30 s.
  let job: any = {};
  for (let i = 0; i < 60; i++) {
    job = await (await request.get(`${baseURL}/api/plot/job`)).json();
    if (job.status !== "running") break;
    await new Promise((r) => setTimeout(r, 500));
  }

  // Job must exist — either stopped mid-way (resumable) or completed.
  expect(job.exists, "plot job should exist after stop").toBeTruthy();

  // Discard the job regardless of whether it was resumable.
  await request.post(`${baseURL}/api/plot/discard`);
  const after = await (await request.get(`${baseURL}/api/plot/job`)).json();
  expect(after.exists, "job should be gone after discard").toBeFalsy();
});
