import { readFileSync } from "fs";
import { join } from "path";
import { test, expect, ASSETS, freshProject, gotoApp, gotoStep, waitForComposition } from "./fixtures";

/** Set up a project with one generated PF layer; returns the layer id. */
async function setupOneLayer(request: any, baseURL: string, name: string): Promise<string> {
  await freshProject(request, baseURL, name);
  await request.post(`${baseURL}/api/image`, {
    multipart: {
      file: { name: "sample.png", mimeType: "image/png", buffer: readFileSync(join(ASSETS, "sample.png")) },
    },
  });
  const add = await (await request.post(`${baseURL}/api/composition/add-layer`, { data: {} })).json();
  const id: string = add.composition.layers.at(-1).id;
  await request.post(`${baseURL}/api/composition/layers/${id}/pathfinding/generate`, {
    data: { pfm_id: "spiral", params: {} },
  });
  return id;
}

// F1: reordering layers with ↑/↓ changes z-order in the composition.
test("F1: layer ↑/↓ buttons reorder the layer list", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E F1");
  await request.post(`${baseURL}/api/image`, {
    multipart: {
      file: { name: "sample.png", mimeType: "image/png", buffer: readFileSync(join(ASSETS, "sample.png")) },
    },
  });
  // Add two layers: A then B (B ends up on top visually / higher index).
  const addA = await (await request.post(`${baseURL}/api/composition/add-layer`, { data: { name: "Layer A" } })).json();
  await request.post(`${baseURL}/api/composition/add-layer`, { data: { name: "Layer B" } });

  await gotoApp(page);

  // Composition panel renders layers top-first (reversed), so B is shown first.
  const layers = page.locator(".layer");
  await expect(layers.first()).toContainText("Layer B");
  await expect(layers.nth(1)).toContainText("Layer A");

  // Click ↓ on Layer B (top slot) to move it below A.
  await page.locator(".layer", { hasText: "Layer B" }).locator('button[title="Move down"]').click();

  // Order should now be A on top, B below.
  await expect(layers.first()).toContainText("Layer A", { timeout: 10_000 });
  await expect(layers.nth(1)).toContainText("Layer B");
});

// F2: unchecking a layer's visibility disables Export and Plot when no layers remain visible.
test("F2: hiding the only layer disables Export and Plot", async ({ page, request, baseURL }) => {
  const id = await setupOneLayer(request, baseURL!, "E2E F2");
  await gotoApp(page);

  // Layer is visible by default → Export SVG is enabled.
  await page.getByRole("button", { name: "File" }).click();
  await expect(page.getByRole("button", { name: "Export SVG" })).toBeEnabled();
  // Close the menu.
  await page.keyboard.press("Escape");

  // Uncheck the layer's visibility checkbox.
  await page.locator(".layer input[type='checkbox']").first().uncheck();

  // All layers hidden → Export and Plot are now disabled.
  await expect(page.locator('button[title="Plot"]')).toBeDisabled({ timeout: 5_000 });
  await page.getByRole("button", { name: "File" }).click();
  await expect(page.getByRole("button", { name: "Export SVG" })).toBeDisabled();
});

// F7: duplicate creates a copy; delete removes it.
test("F7: duplicate and delete layer", async ({ page, request, baseURL }) => {
  const id = await setupOneLayer(request, baseURL!, "E2E F7");
  await gotoApp(page);

  const before = await page.locator(".layer").count();

  // Duplicate the layer.
  await page.locator(".layer").first().locator('button[title="Duplicate"]').click();
  await expect(page.locator(".layer")).toHaveCount(before + 1, { timeout: 10_000 });
  // The copy's name ends with " copy".
  const copy = page.locator(".layer").filter({ hasText: "copy" }).first();
  await expect(copy).toContainText("copy");

  // Delete the copy.
  await copy.locator('button[title="Delete"]').click();
  await expect(page.locator(".layer")).toHaveCount(before, { timeout: 10_000 });
  await expect(page.locator(".layer").first()).not.toContainText("copy");
});

// F3: X/Y numeric inputs in the Composition step move the layer.
test("F3: layer X/Y inputs update position in the backend", async ({ page, request, baseURL }) => {
  const id = await setupOneLayer(request, baseURL!, "E2E F3");
  await gotoApp(page);
  await gotoStep(page, "Composition");

  // Select the layer so position controls appear.
  await page.locator(".layer .pick").first().click();
  await expect(page.locator("#layer-x")).toBeVisible({ timeout: 5_000 });

  // Note the current x from API before changing.
  const before = await (await request.get(`${baseURL}/api/composition`)).json();
  const xBefore: number = before.composition.layers.find((l: { id: string }) => l.id === id)?.x ?? 0;

  // Change X to a different value (move 50mm from origin).
  await page.locator("#layer-x").fill("50");
  await page.locator("#layer-x").press("Tab");

  await page.waitForTimeout(300);
  const after = await (await request.get(`${baseURL}/api/composition`)).json();
  const xAfter: number = after.composition.layers.find((l: { id: string }) => l.id === id)?.x ?? 0;

  // Layer x should have changed from its previous value.
  expect(xAfter).not.toBeCloseTo(xBefore, 0);
});

// F4: Scale % input resizes the layer proportionally.
test("F4: scale % input resizes the layer", async ({ page, request, baseURL }) => {
  const id = await setupOneLayer(request, baseURL!, "E2E F4");
  await gotoApp(page);
  await gotoStep(page, "Composition");

  await page.locator(".layer .pick").first().click();
  await expect(page.locator("#layer-scale")).toBeVisible({ timeout: 5_000 });

  // Halve the size.
  await page.locator("#layer-scale").fill("50");
  await page.locator("#layer-scale").press("Tab");

  await page.waitForTimeout(300);
  const { composition } = await (await request.get(`${baseURL}/api/composition`)).json();
  const layer = composition.layers.find((l: { id: string }) => l.id === id);
  expect(layer?.scale).toBeCloseTo(0.5, 2);
});

// F5: "To content" sets a crop rect on the layer; "Reset" clears it.
test("F5: crop 'To content' sets crop rect; Reset clears it", async ({ page, request, baseURL }) => {
  const id = await setupOneLayer(request, baseURL!, "E2E F5");
  await gotoApp(page);
  await gotoStep(page, "Composition");

  // Select the layer so the X/Y/scale/crop controls appear.
  await page.locator(".layer .pick").first().click();
  await expect(page.locator("#layer-x")).toBeVisible({ timeout: 5_000 });

  // "To content" tightens the crop to the SVG geometry bounding box.
  await page.getByRole("button", { name: "To content" }).click();

  const cropped = await waitForComposition(
    request,
    baseURL!,
    (composition) => composition.layers.find((layer) => layer.id === id)?.crop != null,
    "wait for crop-to-content",
    10_000,
  );
  const layer = cropped.layers.find((layer) => layer.id === id);
  expect(layer?.crop, "'To content' should set a non-null crop rect").not.toBeNull();

  // "Reset" button appears after a crop is applied.
  await expect(page.getByRole("button", { name: "Reset" })).toBeVisible({ timeout: 3_000 });
  await page.getByRole("button", { name: "Reset" }).click();

  const reset = await waitForComposition(
    request,
    baseURL!,
    (composition) => composition.layers.find((layer) => layer.id === id)?.crop === null,
    "wait for crop reset",
    10_000,
  );
  const l2 = reset.layers.find((layer) => layer.id === id);
  expect(l2?.crop, "Reset should clear the crop back to null").toBeNull();
});
