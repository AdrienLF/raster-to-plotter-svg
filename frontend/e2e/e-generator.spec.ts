import {
  test,
  expect,
  DRAWING_SHAPE,
  freshProject,
  getComposition,
  gotoApp,
  gotoGenGroup,
  waitForComposition,
  waitForGeneratedLayer,
} from "./fixtures";

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

// E2: the default generator (spokes_and_circles) generates on explicit request.
test("E2: default generator produces drawing geometry", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E E2");
  await gotoApp(page);

  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });

  await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
  const initial = await waitForGeneratedLayer(request, baseURL!);
  expect(initial.layers[0]?.svg).toMatch(DRAWING_SHAPE);
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
});

// E3: Auto redraws an existing generate layer; disabling it requires an explicit Generate.
test("E3: Auto redraws an existing layer and Auto off requires explicit generation", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E E3");
  await gotoApp(page);

  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });

  await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
  const initial = await waitForGeneratedLayer(request, baseURL!);
  const layerId = initial.layers[0].id;
  const initialSvg = initial.layers[0].svg;
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

  const autoCheck = page.locator("label.auto input[type='checkbox']");
  await expect(autoCheck).toBeChecked();
  await gotoGenGroup(page, "3D Rotation");
  const rot1xInput = page.locator('.ctrl:has(label[for="rot1_x"]) input.numbox');

  // Auto redraw updates the already-selected generate layer after the debounce.
  await rot1xInput.fill("45");
  await rot1xInput.press("Tab");
  const autoRedrawn = await waitForComposition(
    request,
    baseURL!,
    (composition) => {
      const layer = composition.layers.find((candidate) => candidate.id === layerId);
      return layer?.source?.params?.rot1_x === 45 && layer.svg !== initialSvg;
    },
    "wait for debounced auto redraw",
    60_000,
  );
  const autoSvg = autoRedrawn.layers.find((layer) => layer.id === layerId)!.svg;
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

  // With Auto off, changing a parameter does not update the persisted layer.
  await autoCheck.uncheck();
  await rot1xInput.fill("15");
  await rot1xInput.press("Tab");
  await page.waitForTimeout(600);
  const unchanged = (await getComposition(request, baseURL!)).layers.find((layer) => layer.id === layerId)!;
  expect(unchanged.svg, "Auto off should preserve the current SVG").toBe(autoSvg);
  expect(unchanged.source.params.rot1_x, "Auto off should preserve persisted params").toBe(45);

  // Explicit generation applies the pending parameter to that same layer — but the
  // layer already has art, so confirm the overwrite warning.
  await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
  await page
    .getByRole("dialog", { name: "Layer already generated" })
    .getByRole("button", { name: "Overwrite this layer" })
    .click();
  const explicitlyRedrawn = await waitForComposition(
    request,
    baseURL!,
    (composition) => {
      const layer = composition.layers.find((candidate) => candidate.id === layerId);
      return layer?.source?.params?.rot1_x === 15 && layer.svg !== autoSvg;
    },
    "wait for explicit redraw with Auto off",
    60_000,
  );
  expect(explicitlyRedrawn.layers.find((layer) => layer.id === layerId)?.id).toBe(layerId);
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
});

// E4: changing a framework knob (rot1_x) visibly alters output; same params → same SVG (determinism).
test("E4: rot1_x knob changes output; reverting produces the same SVG (deterministic)", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E E4");
  await gotoApp(page);

  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });
  await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
  const initial = await waitForGeneratedLayer(request, baseURL!);
  const svg1: string = initial.layers[0]?.svg ?? "";
  expect(svg1, "initial generate must produce geometry").toMatch(DRAWING_SHAPE);
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

  // Change rot1_x (3D Rotation group) — auto-redraw fires after 350ms debounce.
  await gotoGenGroup(page, "3D Rotation");
  const rot1xInput = page.locator('.ctrl:has(label[for="rot1_x"]) input.numbox');
  await rot1xInput.fill("45");
  await rot1xInput.press("Tab");
  const changed = await waitForComposition(
    request,
    baseURL!,
    (composition) => {
      const svg = composition.layers[0]?.svg ?? "";
      return svg.length > 0 && svg !== svg1;
    },
    "wait for rot1_x geometry change",
    60_000,
  );
  const svg2: string = changed.layers[0]?.svg ?? "";
  expect(svg2, "rot1_x=45 should produce different geometry").not.toBe(svg1);
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

  // Revert rot1_x to 0 → same params as the initial run → deterministic output.
  await rot1xInput.fill("0");
  await rot1xInput.press("Tab");
  const reverted = await waitForComposition(
    request,
    baseURL!,
    (composition) => (composition.layers[0]?.svg ?? "") === svg1,
    "wait for deterministic geometry revert",
    60_000,
  );
  const svg3: string = reverted.layers[0]?.svg ?? "";
  expect(svg3, "same params + same seed must produce the same SVG").toBe(svg1);
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
});

// E6 [P]: generate timing — spokes_and_circles with defaults should finish within soft budget.
test("E6: spokes_and_circles generate timing", async ({ page, request, baseURL, recordPerf }) => {
  await freshProject(request, baseURL!, "E2E E6");
  await gotoApp(page);

  const t0 = Date.now();
  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });
  await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
  await waitForGeneratedLayer(request, baseURL!);
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
  const duration_ms = Date.now() - t0;

  recordPerf({ story: "E6", duration_ms });
  const budget = 5_000;
  if (duration_ms > budget) console.warn(`[perf] E6: generate ${duration_ms}ms > budget ${budget}ms (soft)`);
  console.log(`[perf] E6: spokes_and_circles ${duration_ms}ms`);
});

// E7 [U]: Generate panel — params are organized into named group tabs for scannability.
test("E7: generator params are organized into named group tabs", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E E7");
  await gotoApp(page);

  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });

  // Groups are surfaced as a tab strip; only the active group's params render.
  const groupCount = await page.locator(".tabs button").count();
  expect(groupCount, "params should be organized into group tabs").toBeGreaterThan(0);

  console.log(`[ux] E7: ${groupCount} param group tabs in GeneratePanel`);
  // The framework alone has ~10+ groups (Decimate, Transform, 3D Rotation, Distort 1/2, …).
  expect(groupCount, "should have multiple group tabs for scannability").toBeGreaterThanOrEqual(3);
});

// E8: Shape Field uses its dedicated dynamic editor and persists the shape stack.
test("E8: Shape Field dedicated editor builds and persists a dynamic pattern", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E E8 Shape Field");
  await gotoApp(page);

  await page.getByRole("button", { name: "＋ Generator" }).click();
  await page.locator(".gen-select").selectOption("shape_field");
  await expect(page.locator(".shape-field-editor")).toBeVisible();
  await expect(page.locator(".shape-card")).toHaveCount(3);

  await page.getByRole("button", { name: "Add shape" }).click();
  await expect(page.locator(".shape-card")).toHaveCount(4);
  await page.getByRole("button", { name: "✦ Generate", exact: true }).click();

  const composition = await waitForGeneratedLayer(request, baseURL!);
  const layer = composition.layers[0];
  expect(layer.svg).toMatch(DRAWING_SHAPE);
  expect(layer.source.generator_id).toBe("shape_field");
  expect(layer.source.params.shape_layers).toHaveLength(4);
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
});

// E5: the target selector generates into a new layer or updates an existing one in place.
test("E5: target selector — new layer vs existing layer", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E E5");
  await gotoApp(page);

  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });
  await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
  const initial = await waitForComposition(
    request,
    baseURL!,
    (composition) => composition.layers.length === 1 && DRAWING_SHAPE.test(composition.layers[0]?.svg ?? ""),
    "wait for initial target layer generation",
    60_000,
  );
  const firstLayerId: string = initial.layers[0].id;
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

  // "＋ New layer" calls api.newLayer() which clears the selection (selected_layer_id = null).
  // Generating with no selection adds a brand-new layer.
  const targetSelect = page.locator("label.target select");
  await targetSelect.selectOption("__new__");
  await waitForComposition(
    request,
    baseURL!,
    (composition) => composition.selected_layer_id === null,
    "wait for new-layer target selection",
    10_000,
  );
  await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
  const withNewLayer = await waitForComposition(
    request,
    baseURL!,
    (composition) => composition.layers.length === 2,
    "wait for generation into a new layer",
    60_000,
  );
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

  // Select the original layer and disable Auto so the parameter change stays pending.
  await targetSelect.selectOption(firstLayerId);
  const selected = await waitForComposition(
    request,
    baseURL!,
    (composition) => composition.selected_layer_id === firstLayerId,
    "wait for original target selection",
    10_000,
  );
  const autoCheck = page.locator("label.auto input[type='checkbox']");
  await expect(autoCheck).toBeChecked();
  await autoCheck.uncheck();

  const originalLayer = selected.layers.find((layer) => layer.id === firstLayerId)!;
  const originalSvg = originalLayer.svg;
  const stableLayerIds = withNewLayer.layers.map((layer) => layer.id).sort();
  await gotoGenGroup(page, "3D Rotation");
  const rot1xInput = page.locator('.ctrl:has(label[for="rot1_x"]) input.numbox');
  await rot1xInput.fill("60");
  await rot1xInput.press("Tab");
  await page.waitForTimeout(600);
  const beforeExplicit = (await getComposition(request, baseURL!)).layers.find(
    (layer) => layer.id === firstLayerId,
  )!;
  expect(beforeExplicit.svg, "Auto off should not regenerate the selected target").toBe(originalSvg);
  expect(beforeExplicit.source.params.rot1_x).not.toBe(60);

  // Generate replaces the original layer in place while preserving both layer IDs —
  // the selected layer already has art, so confirm the overwrite warning.
  await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
  await page
    .getByRole("dialog", { name: "Layer already generated" })
    .getByRole("button", { name: "Overwrite this layer" })
    .click();
  const updated = await waitForComposition(
    request,
    baseURL!,
    (composition) => {
      const layer = composition.layers.find((candidate) => candidate.id === firstLayerId);
      const ids = composition.layers.map((candidate) => candidate.id).sort();
      return (
        composition.layers.length === 2 &&
        ids.every((id, index) => id === stableLayerIds[index]) &&
        layer?.source?.params?.rot1_x === 60 &&
        layer.svg !== originalSvg
      );
    },
    "wait for observable in-place generator update",
    60_000,
  );
  expect(updated.layers).toHaveLength(2);
  expect(updated.layers.map((layer) => layer.id).sort()).toEqual(stableLayerIds);
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
});

// E9: switching generators never auto-redraws; ✦ Generate warns before overwriting
// a layer that already has a generation and can spawn a fresh layer instead.
test("E9: generator switch waits for Generate; overwrite warning offers a new layer", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E E9");
  await gotoApp(page);

  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });
  await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
  const initial = await waitForGeneratedLayer(request, baseURL!);
  const layerId = initial.layers[0].id;
  const originalGen = initial.layers[0].source.generator_id;
  expect(originalGen).toBe("spokes_and_circles");
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

  // Auto is on by default — switching the generator must NOT regenerate.
  await expect(page.locator("label.auto input[type='checkbox']")).toBeChecked();
  await page.locator(".gen-select").selectOption("shape_field");
  await page.waitForTimeout(800); // well past the 350ms auto-redraw debounce
  const afterSwitch = await getComposition(request, baseURL!);
  expect(
    afterSwitch.layers.find((layer) => layer.id === layerId)?.source.generator_id,
    "switching generators alone must not regenerate the layer",
  ).toBe(originalGen);

  // Pressing ✦ Generate on a layer that already has art opens the warning dialog.
  await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Layer already generated" });
  await expect(dialog).toBeVisible();

  // "Create new layer" generates into a fresh layer; the original keeps its generator.
  await dialog.getByRole("button", { name: "Create new layer" }).click();
  const withNew = await waitForComposition(
    request,
    baseURL!,
    (composition) => composition.layers.length === 2,
    "wait for a new layer from the overwrite dialog",
    60_000,
  );
  expect(withNew.layers.find((layer) => layer.id === layerId)?.source.generator_id).toBe(originalGen);
  expect(withNew.layers.find((layer) => layer.id !== layerId)?.source.generator_id).toBe("shape_field");
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
});

// E10: Spokes & Circles distributes the drawing-set's pens across elements — the
// generated layer's SVG carries one Inkscape pen group per active pen colour.
test("E10: spokes_and_circles cycles pens across spokes/circles", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E E10");
  // Three enabled pens, distinct colours.
  const pen = (name: string, colour: string) => ({
    name, type: "Generic", colour, weight: 1, stroke_mm: 0.5, enabled: true,
  });
  await request.post(`${baseURL}/api/pens`, {
    data: {
      pens: [pen("P1", "#ff0000"), pen("P2", "#00ff00"), pen("P3", "#0000ff")],
      distribution_type: "luminance",
      distribution_order: "darkest",
    },
  });
  await gotoApp(page);

  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });

  // Enable pen cycling in the new Pens tab, then generate (no layer selected yet).
  await gotoGenGroup(page, "Pens");
  await page.getByRole("checkbox", { name: "Pen Cycle" }).check();
  await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
  await waitForGeneratedLayer(request, baseURL!);
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });

  const composition = await getComposition(request, baseURL!);
  const svg = composition.layers[0]?.svg ?? "";
  const groups = (svg.match(/inkscape:groupmode="layer"/g) ?? []).length;
  expect(groups, "one pen layer group per used pen").toBeGreaterThanOrEqual(3);
  for (const colour of ["#ff0000", "#00ff00", "#0000ff"]) {
    expect(svg, `pen ${colour} should appear`).toContain(colour);
  }
});

// E11: editing a pen re-runs the generator so its pen cycle re-maps to the new
// pen list (no explicit ✦ Generate needed).
test("E11: editing a pen recalculates the generator pen cycle", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E E11");
  const pen = (name: string, colour: string) => ({
    name, type: "Generic", colour, weight: 1, stroke_mm: 0.5, enabled: true,
  });
  await request.post(`${baseURL}/api/pens`, {
    data: {
      pens: [pen("P1", "#ff0000"), pen("P2", "#00ff00")],
      distribution_type: "luminance",
      distribution_order: "darkest",
    },
  });
  await gotoApp(page);

  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });
  await gotoGenGroup(page, "Pens");
  await page.getByRole("checkbox", { name: "Pen Cycle" }).check();
  await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
  await waitForGeneratedLayer(request, baseURL!);
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
  expect((await getComposition(request, baseURL!)).layers[0].svg).toContain("#ff0000");

  // Recolour the first pen via the Pens panel — saving should re-run the generator.
  await page.locator('.pen input[type="color"]').first().evaluate((el, v) => {
    const input = el as HTMLInputElement;
    input.value = v as string;
    input.dispatchEvent(new Event("input", { bubbles: true }));   // updates bind:value
    input.dispatchEvent(new Event("change", { bubbles: true }));  // triggers save()
  }, "#123456");

  await waitForComposition(
    request,
    baseURL!,
    (composition) => (composition.layers[0]?.svg ?? "").includes("#123456"),
    "wait for the pen-edit recalc",
    60_000,
  );
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
});
