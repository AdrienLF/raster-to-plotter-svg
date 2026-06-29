import { readFileSync } from "fs";
import { join } from "path";
import { test, expect, ASSETS, freshProject, gotoApp } from "./fixtures";

/** Create a project with a generated spiral layer and return composition data. */
async function setupLayerProject(request: any, baseURL: string, name: string) {
  await freshProject(request, baseURL, name);
  await request.post(`${baseURL}/api/image`, {
    multipart: {
      file: { name: "sample.png", mimeType: "image/png", buffer: readFileSync(join(ASSETS, "sample.png")) },
    },
  });
  const add = await (await request.post(`${baseURL}/api/composition/add-layer`, { data: {} })).json();
  const layerId: string = add.composition.layers.at(-1).id;
  await request.post(`${baseURL}/api/composition/layers/${layerId}/pathfinding/generate`, {
    data: { pfm_id: "spiral", params: {} },
  });
  return { layerId, composition: add.composition };
}

// J1: export SVG downloads a valid SVG document.
test("J1: export SVG returns valid SVG content", async ({ request, baseURL }) => {
  await setupLayerProject(request, baseURL!, "E2E J1");

  const r = await request.get(`${baseURL}/api/export`);
  expect(r.ok(), "export should succeed").toBeTruthy();
  expect(r.headers()["content-type"]).toMatch(/svg/i);

  const body = await r.text();
  expect(body).toMatch(/^<svg\s/);
  expect(body).toContain("</svg>");
});

// J2: export with split=1 downloads a zip containing per-layer SVG files.
test("J2: export layers (zip) returns application/zip", async ({ request, baseURL }) => {
  await setupLayerProject(request, baseURL!, "E2E J2");

  const r = await request.get(`${baseURL}/api/export?split=1`);
  expect(r.ok(), "zip export should succeed").toBeTruthy();
  expect(r.headers()["content-type"]).toMatch(/zip/i);

  // Zip files start with PK (0x50 0x4B).
  const body = await r.body();
  expect(body[0]).toBe(0x50);
  expect(body[1]).toBe(0x4b);
});

// J3: exported SVG dimensions match the composition page (default A3: 297x420mm).
test("J3: exported SVG width/height match the composition page", async ({ request, baseURL }) => {
  await setupLayerProject(request, baseURL!, "E2E J3");

  // Read the current composition page so the assertion doesn't hard-code a preset.
  const { composition } = await (await request.get(`${baseURL}/api/composition`)).json();
  const w: number = composition.page.width;
  const h: number = composition.page.height;

  const r = await request.get(`${baseURL}/api/export`);
  const svg = await r.text();

  // _fmt(297.0) → "297"; check the SVG header carries the page dimensions in mm.
  expect(svg).toContain(`width="${w}mm"`);
  expect(svg).toContain(`height="${h}mm"`);
});

// J5 [P]: export time for a multi-layer drawing stays within soft budget.
test("J5: export SVG latency for a multi-layer drawing", async ({ request, baseURL, recordPerf }) => {
  await freshProject(request, baseURL!, "E2E J5");
  await request.post(`${baseURL}/api/image`, {
    multipart: {
      file: { name: "sample.png", mimeType: "image/png", buffer: readFileSync(join(ASSETS, "sample.png")) },
    },
  });
  // Two layers with moderate density for a "heavy" export fixture.
  for (const pfm of ["voronoi_stippling", "hatch"] as const) {
    const add = await (await request.post(`${baseURL}/api/composition/add-layer`, { data: {} })).json();
    const lid: string = add.composition.layers.at(-1).id;
    await request.post(`${baseURL}/api/composition/layers/${lid}/pathfinding/generate`, {
      data: { pfm_id: pfm, params: pfm === "voronoi_stippling" ? { point_density: 500 } : {} },
    });
  }

  const t0 = Date.now();
  const r = await request.get(`${baseURL}/api/export`);
  const duration_ms = Date.now() - t0;
  expect(r.ok(), "export should succeed").toBeTruthy();
  expect((await r.text())).toMatch(/^<svg\s/);

  recordPerf({ story: "J5", duration_ms });
  const budget = 5_000;
  if (duration_ms > budget) console.warn(`[perf] J5: export ${duration_ms}ms > budget ${budget}ms (soft)`);
  console.log(`[perf] J5: export ${duration_ms}ms`);
});

// J6: File → Export SVG triggers a client-side download (fetch + blob path).
test("J6: Export SVG menu action downloads plot.svg", async ({ page, request, baseURL }) => {
  await setupLayerProject(request, baseURL!, "E2E J6");
  await gotoApp(page);

  await page.getByRole("button", { name: "File" }).click();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export SVG" }).click();
  const download = await downloadPromise;

  expect(download.suggestedFilename()).toBe("plot.svg");
});

// J4: hidden layers are excluded — when all layers are hidden, Export is disabled in the UI.
// (The API would fall back to _drawing; the UI gate is the user-visible protection.)
test("J4: hidden-only composition disables Export SVG in the UI", async ({ page, request, baseURL }) => {
  await setupLayerProject(request, baseURL!, "E2E J4");
  await gotoApp(page);

  // Layer is visible by default.
  await page.getByRole("button", { name: "File" }).click();
  await expect(page.getByRole("button", { name: "Export SVG" })).toBeEnabled();
  await page.keyboard.press("Escape");

  // Hide the layer.
  await page.locator(".layer input[type='checkbox']").first().uncheck();

  // Export should now be disabled (hasVisibleLayers = false).
  await expect(page.locator('button[title="Plot"]')).toBeDisabled({ timeout: 5_000 });
  await page.getByRole("button", { name: "File" }).click();
  await expect(page.getByRole("button", { name: "Export SVG" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Export layers (zip)" })).toBeDisabled();
});
