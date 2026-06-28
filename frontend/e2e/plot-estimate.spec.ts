import { readFileSync } from "fs";
import { join } from "path";
import { test, expect, ASSETS, gotoApp, gotoStep, freshProject } from "./fixtures";

// Stories K1 (estimate, no hardware) + K5 (start plot against the fake Grbl serial).
//
// Setup (image + a light single-path "spiral" layer) is done via the API for
// speed and isolation; the estimate and Start interactions are driven through
// the real UI. Spiral = one path, so the plot is quick and gentle.
test("K1+K5: estimate, then plot against the fake serial", async ({ page, request, baseURL }) => {
  const api = (p: string) => `${baseURL}${p}`;

  await freshProject(request, baseURL!, "E2E Plot");
  await request.post(api("/api/image"), {
    multipart: {
      file: { name: "sample.png", mimeType: "image/png", buffer: readFileSync(join(ASSETS, "sample.png")) },
    },
  });
  const add = await (await request.post(api("/api/composition/add-layer"), { data: {} })).json();
  const layerId: string = add.composition.layers.at(-1).id;
  const gen = await request.post(api(`/api/composition/layers/${layerId}/pathfinding/generate`), {
    data: { pfm_id: "spiral", params: {} },
  });
  expect(gen.ok(), "spiral layer generated").toBeTruthy();

  await gotoApp(page);

  // K1 — Plot step auto-refreshes the estimate; observe that request and rendered metric.
  const estimateResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/plot/estimate") &&
      response.request().method() === "GET",
    { timeout: 60_000 },
  );
  await gotoStep(page, "Plot");
  const estimateResponse = await estimateResponsePromise;
  expect(estimateResponse.ok(), "plot estimate response should succeed").toBeTruthy();
  const estimate = await estimateResponse.json();
  expect(estimate.paths, "plot estimate should report paths").toBeGreaterThan(0);
  const paths = page.locator(".metrics div", { hasText: "Paths" }).locator("strong");
  await expect(paths).not.toHaveText("—", { timeout: 10_000 });

  // Reset captured G-code so the assertion below only sees this plot's commands.
  await request.delete(api("/api/_test/serial-log"));

  // K5 — Start the plot; it runs entirely against the in-memory fake serial.
  await page.getByRole("button", { name: "Start", exact: true }).click();
  await expect(page.locator(".status .state")).toHaveText("Done", { timeout: 60_000 });

  // Proof it actually drove the (fake) plotter: real Grbl G-code was emitted.
  const log = await (await request.get(api("/api/_test/serial-log"))).json();
  expect(log.writes.some((c: string) => c.startsWith("G01") || c.startsWith("G00"))).toBeTruthy();
  expect(log.writes).toContain("$H"); // homing cycle
});
