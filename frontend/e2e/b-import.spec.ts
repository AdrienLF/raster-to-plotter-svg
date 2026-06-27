import { readFileSync } from "fs";
import { join } from "path";
import { test, expect, ASSETS, freshProject, gotoApp } from "./fixtures";

// B2: the ToolRail 🖼 button opens the same file chooser as the menu.
test("B2: ToolRail import button triggers file chooser and loads image", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E B2");
  await gotoApp(page);

  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.locator('button[title="Import image"]').click(),
  ]);
  await chooser.setFiles(join(ASSETS, "sample.png"));

  await expect(page.locator('button[title="Run path finding"]')).toBeEnabled({ timeout: 15_000 });
  await expect(page.locator(".menubar")).toContainText("sample.png");
});

// B3: uploading an .svg file routes to a composition SVG layer, not a raster source.
// Run path finding stays disabled (no imageUrl); Export becomes enabled (layer exists).
test("B3: SVG upload becomes a composition layer, not a raster source", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E B3");
  await gotoApp(page);

  await page.locator('input[type="file"]').setInputFiles(join(ASSETS, "sample.svg"));
  await expect(page.locator(".menubar")).toContainText("sample.svg", { timeout: 10_000 });

  // No raster source → Run path finding stays disabled.
  await expect(page.locator('button[title="Run path finding"]')).toBeDisabled();

  // But a composition layer exists → Export SVG is enabled.
  await page.getByRole("button", { name: "File" }).click();
  await expect(page.getByRole("button", { name: "Export SVG" })).toBeEnabled();
});

// B4: importing a second image replaces the first (menubar name updates, imageUrl is refreshed).
test("B4: re-import replaces the raster source", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E B4");
  await gotoApp(page);

  await page.locator('input[type="file"]').setInputFiles(join(ASSETS, "sample.png"));
  await expect(page.locator(".menubar")).toContainText("sample.png", { timeout: 10_000 });

  // Re-import (same fixture; what matters is the imageUrl is refreshed and button stays enabled).
  // ponytail: only one raster fixture available; the important invariant is re-import works at all.
  await page.locator('input[type="file"]').setInputFiles(join(ASSETS, "sample.png"));
  await expect(page.locator('button[title="Run path finding"]')).toBeEnabled({ timeout: 10_000 });
  await expect(page.locator(".menubar")).toContainText("sample.png");
});

// B6: unsupported file types are rejected at the API with a 400.
// UX: the browser UI currently gives no visible error feedback (silent rejection — worth addressing).
test("B6: unsupported file type rejected by API", async ({ request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E B6");
  const r = await request.post(`${baseURL}/api/image`, {
    multipart: {
      file: { name: "test.txt", mimeType: "text/plain", buffer: Buffer.from("not an image") },
    },
  });
  expect(r.status()).toBe(400);
  const j = await r.json();
  expect(j.error).toMatch(/not a readable image/i);
});

// B5 [P]: large image (6000×4000) upload stays within soft budget; viewport stays responsive.
test("B5: large image upload performance", async ({ request, baseURL, recordPerf }) => {
  await freshProject(request, baseURL!, "E2E B5");

  const t0 = Date.now();
  const r = await request.post(`${baseURL}/api/image`, {
    multipart: {
      file: { name: "large.jpg", mimeType: "image/jpeg", buffer: readFileSync(join(ASSETS, "large.jpg")) },
    },
  });
  const duration_ms = Date.now() - t0;
  expect(r.ok(), "large image upload should succeed").toBeTruthy();

  recordPerf({ story: "B5", duration_ms });
  const budget = 20_000; // 20 s soft budget for a 375 KB JPEG of 6000×4000
  if (duration_ms > budget) console.warn(`[perf] B5: upload ${duration_ms}ms > budget ${budget}ms (soft)`);
  console.log(`[perf] B5: upload ${duration_ms}ms`);
});
