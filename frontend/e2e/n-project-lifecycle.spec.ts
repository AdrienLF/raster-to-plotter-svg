import { test, expect, gotoApp } from "./fixtures";
import type { APIRequestContext, Page } from "@playwright/test";

async function createProject(request: APIRequestContext, baseURL: string, name: string) {
  const response = await request.post(`${baseURL}/api/projects`, { data: { name } });
  expect(response.ok(), `create ${name}`).toBeTruthy();
  return (await response.json()).current.id as string;
}

async function nextPaint(page: Page) {
  await page.evaluate(
    () => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))),
  );
}

test("N1: the latest rapid project switch wins over an older delayed boot", async ({ page, request, baseURL }) => {
  await createProject(request, baseURL!, "Lifecycle Alpha");
  await createProject(request, baseURL!, "Lifecycle Beta");
  await createProject(request, baseURL!, "Lifecycle Current");
  await gotoApp(page);

  let releaseOlderBoot!: () => void;
  const olderBootReleased = new Promise<void>((resolve) => (releaseOlderBoot = resolve));
  let markOlderBootCaptured!: () => void;
  const olderBootCaptured = new Promise<void>((resolve) => (markOlderBootCaptured = resolve));
  let holdNextProjectsRead = true;

  await page.route("**/api/projects", async (route) => {
    const requestUrl = new URL(route.request().url());
    if (holdNextProjectsRead && route.request().method() === "GET" && requestUrl.pathname === "/api/projects") {
      holdNextProjectsRead = false;
      const response = await route.fetch();
      markOlderBootCaptured();
      await olderBootReleased;
      await route.fulfill({ response });
      return;
    }
    await route.continue();
  });

  await page.getByRole("button", { name: "Project" }).click();
  await page.getByRole("button", { name: "Lifecycle Alpha", exact: true }).click();
  await olderBootCaptured;

  const latestBootFinished = page.waitForResponse(
    (response) => response.url().includes("/api/versions") && response.request().method() === "GET",
  );
  await page.getByRole("button", { name: "Project" }).click();
  await page.getByRole("button", { name: "Lifecycle Beta", exact: true }).click();
  await latestBootFinished;
  await nextPaint(page);
  await expect(page.locator(".menubar")).toContainText("Lifecycle Beta");

  const olderProjectsResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/projects") && response.request().method() === "GET",
  );
  releaseOlderBoot();
  await olderProjectsResponse;
  await nextPaint(page);

  await expect(page.locator(".menubar")).toContainText("Lifecycle Beta");
  await expect(page.locator(".menubar")).not.toContainText("Lifecycle Alpha");
});

test("N2: a project-switch boot failure is surfaced without an unhandled rejection", async ({ page, request, baseURL }) => {
  await createProject(request, baseURL!, "Lifecycle Failure Target");
  await createProject(request, baseURL!, "Lifecycle Failure Current");
  await gotoApp(page);

  const pageErrors: Error[] = [];
  page.on("pageerror", (error) => pageErrors.push(error));
  let failNextPfmList = true;
  await page.route("**/api/pfm/list", async (route) => {
    if (failNextPfmList) {
      failNextPfmList = false;
      await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: "boot failed" }) });
      return;
    }
    await route.continue();
  });

  await page.getByRole("button", { name: "Project" }).click();
  await page.getByRole("button", { name: "Lifecycle Failure Target", exact: true }).click();

  await expect(page.locator(".status .state")).toHaveText("Boot error: boot failed");
  await expect(page.locator(".status .log")).toContainText("Boot error: boot failed");
  expect(pageErrors).toEqual([]);
});
