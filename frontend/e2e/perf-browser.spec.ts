import { readFileSync } from "fs";
import { join } from "path";
import { test, expect, ASSETS, freshProject, gotoApp } from "./fixtures";


test("performance: application boot", async ({ page, request, baseURL, recordPerf }) => {
  await freshProject(request, baseURL!, "Perf browser boot");
  const started = Date.now();
  await gotoApp(page);
  recordPerf({
    story: "BROWSER",
    workload: "browser.boot",
    fixture: "empty-project-v1",
    backend: "chromium",
    duration_ms: Date.now() - started,
  });
});


test("performance: large SVG viewport render", async ({ page, request, baseURL, recordPerf }) => {
  await freshProject(request, baseURL!, "Perf large viewport");
  await request.post(`${baseURL}/api/image`, {
    multipart: {
      file: { name: "sample.png", mimeType: "image/png",
              buffer: readFileSync(join(ASSETS, "sample.png")) },
    },
  });
  const added = await (await request.post(`${baseURL}/api/composition/add-layer`, { data: {} })).json();
  const layerId: string = added.composition.layers.at(-1).id;
  const generated = await request.post(
    `${baseURL}/api/composition/layers/${layerId}/pathfinding/generate`,
    { data: { pfm_id: "voronoi_stippling", params: { point_density: 800 } } },
  );
  expect(generated.ok()).toBeTruthy();
  const body = await generated.json();
  const layer = body.composition.layers.find((item: { id: string }) => item.id === layerId);
  const shapes = (String(layer.svg).match(/<(circle|path|line|polyline|polygon|rect)\b/g) || []).length;
  expect(shapes).toBeGreaterThan(0);

  const started = Date.now();
  await gotoApp(page);
  const image = page.locator(".layer-paths").first();
  await expect(image).toBeVisible();
  await image.evaluate((element: HTMLImageElement) => element.decode());
  recordPerf({
    story: "BROWSER",
    workload: "browser.large_viewport",
    fixture: "voronoi-800-v1",
    backend: "chromium",
    duration_ms: Date.now() - started,
    shapes,
    metrics: { shapes },
  });
});
