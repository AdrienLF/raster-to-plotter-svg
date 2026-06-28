import { test, expect, freshProject, gotoApp } from "./fixtures";

// E1: "＋ Generator" button navigates to the Generate step.
test("E1: ＋ Generator button navigates to the Generate step", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E E1");
  await gotoApp(page);

  await page.getByRole("button", { name: "＋ Generator" }).click();

  // The "Generate" step tab should become active.
  await expect(page.getByRole("tab", { name: "Generate" })).toHaveAttribute("aria-selected", "true");
  // The GeneratePanel mounts — the generator select is the entry point.
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });
});

// E2: default generator (spokes_and_circles) auto-generates when Auto is on.
test("E2: Auto-redraw generates on Generate step entry", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E E2");
  await gotoApp(page);

  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });

  // Auto is true by default; debounce fires after 350ms.
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

  // The layer should now have SVG geometry.
  const { composition } = await (await request.get(`${baseURL}/api/composition`)).json();
  expect(composition.layers[0]?.svg).toMatch(/<(path|line|polyline|circle)\b/);
});

// E3: unchecking Auto suppresses auto-redraw; explicit Generate still works.
test("E3: Auto off suppresses auto-redraw; explicit Generate triggers generation", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E E3");
  await gotoApp(page);

  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });

  // Uncheck Auto before the 350ms debounce fires.
  const autoCheck = page.locator("label.auto input[type='checkbox']");
  await expect(autoCheck).toBeChecked();
  await autoCheck.uncheck();

  // Wait longer than the debounce; status should remain Idle.
  await page.waitForTimeout(600);
  await expect(page.locator(".status .state")).toHaveText("Idle");

  // Explicit click → generation completes.
  await page.getByRole("button", { name: "Generate" }).click();
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
});

// E4: changing a framework knob (rot1_x) visibly alters output; same params → same SVG (determinism).
test("E4: rot1_x knob changes output; reverting produces the same SVG (deterministic)", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E E4");
  await gotoApp(page);

  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

  const { composition: c1 } = await (await request.get(`${baseURL}/api/composition`)).json();
  const svg1: string = c1.layers[0]?.svg ?? "";
  expect(svg1).toMatch(/<(path|line|polyline|circle)\b/, "initial generate must produce geometry");

  // Change rot1_x (3D Rotation group) — auto-redraw fires after 350ms debounce.
  const rot1xInput = page.locator('.ctrl:has(label[for="rot1_x"]) input.numbox');
  await rot1xInput.fill("45");
  await rot1xInput.press("Tab");
  await page.waitForTimeout(500); // let the 350ms debounce fire before checking Ready
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

  const { composition: c2 } = await (await request.get(`${baseURL}/api/composition`)).json();
  const svg2: string = c2.layers[0]?.svg ?? "";
  expect(svg2, "rot1_x=45 should produce different geometry").not.toBe(svg1);

  // Revert rot1_x to 0 → same params as the initial run → deterministic output.
  await rot1xInput.fill("0");
  await rot1xInput.press("Tab");
  await page.waitForTimeout(500);
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

  const { composition: c3 } = await (await request.get(`${baseURL}/api/composition`)).json();
  const svg3: string = c3.layers[0]?.svg ?? "";
  expect(svg3, "same params + same seed must produce the same SVG").toBe(svg1);
});

// E6 [P]: generate timing — spokes_and_circles with defaults should finish within soft budget.
test("E6: spokes_and_circles generate timing", async ({ page, request, baseURL, recordPerf }) => {
  await freshProject(request, baseURL!, "E2E E6");
  await gotoApp(page);

  const t0 = Date.now();
  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
  const duration_ms = Date.now() - t0;

  recordPerf({ story: "E6", duration_ms });
  const budget = 5_000;
  if (duration_ms > budget) console.warn(`[perf] E6: generate ${duration_ms}ms > budget ${budget}ms (soft)`);
  console.log(`[perf] E6: spokes_and_circles ${duration_ms}ms`);
});

// E7 [U]: Generate panel — params are organized into named groups for scannability.
test("E7: generator params are organized into named groups", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E E7");
  await gotoApp(page);

  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });

  // Params render inside .group containers with .group-title headings.
  const groupCount = await page.locator(".group-title").count();
  expect(groupCount, "params should be organized into groups").toBeGreaterThan(0);

  console.log(`[ux] E7: ${groupCount} param groups in GeneratePanel`);
  // The framework alone has ~10+ groups (Decimate, Transform, 3D Rotation, Distort 1/2, …).
  expect(groupCount, "should have multiple groups for scannability").toBeGreaterThanOrEqual(3);
});

// E5: the target selector generates into a new layer or updates an existing one in place.
test("E5: target selector — new layer vs existing layer", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E E5");
  await gotoApp(page);

  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

  // One layer after the initial auto-generate.
  expect(await page.locator(".layer").count()).toBe(1);
  const { composition: c1 } = await (await request.get(`${baseURL}/api/composition`)).json();
  const firstLayerId: string = c1.layers[0].id;

  // "＋ New layer" calls api.newLayer() which clears the selection (selected_layer_id = null).
  // Generating with no selection adds a brand-new layer.
  const targetSelect = page.locator("label.target select");
  await targetSelect.selectOption("__new__");
  await page.getByRole("button", { name: "Generate" }).click();
  await page.waitForTimeout(500);
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
  expect(await page.locator(".layer").count()).toBe(2);

  // Select the original layer → generate replaces it in place (no new layer created).
  await targetSelect.selectOption(firstLayerId);
  await page.getByRole("button", { name: "Generate" }).click();
  await page.waitForTimeout(500);
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
  expect(await page.locator(".layer").count()).toBe(2);
});
