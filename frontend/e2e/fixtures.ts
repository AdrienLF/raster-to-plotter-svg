import { test as base, expect, type APIRequestContext, type Page, type Request } from "@playwright/test";
import { appendFileSync, mkdirSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
import type { CompositionT } from "../src/lib/types";

const HERE = dirname(fileURLToPath(import.meta.url));
export const ASSETS = join(HERE, "assets");
const PERF_FILE = join(HERE, "perf", "results.jsonl");
export const DRAWING_SHAPE = /<(?:[A-Za-z_][\w.-]*:)?(?:path|line|polyline|circle)(?=[\s/>])/;
const BOOT_ATTEMPT_TIMEOUT = 10_000;

type BootOutcome =
  | { kind: "ready" }
  | { kind: "error"; log: string }
  | { kind: "timeout" }
  | { kind: "navigation-error"; log: string };
type BootRequestFailure = { url: string; error: string };

function isTransientBootFailure(log: string, failures: BootRequestFailure[]) {
  return (
    log.endsWith("Boot error: Failed to fetch") &&
    failures.some((failure) => failure.url.includes("/api/"))
  );
}

async function runBootAttempt(
  page: Page,
  navigate: () => Promise<unknown>,
): Promise<BootOutcome> {
  const ready = page
    .waitForResponse(
      (response) =>
        response.url().endsWith("/api/versions") &&
        response.request().method() === "GET" &&
        response.ok(),
      { timeout: BOOT_ATTEMPT_TIMEOUT },
    )
    .then(() => ({ kind: "ready" }) as const)
    .catch(() => ({ kind: "timeout" }) as const);

  try {
    await navigate();
  } catch (error) {
    return {
      kind: "navigation-error",
      log: error instanceof Error ? error.message : String(error),
    };
  }

  const bootError = page
    .locator(".status .log")
    .filter({ hasText: "Boot error:" });
  const failed = bootError
    .waitFor({ state: "visible", timeout: BOOT_ATTEMPT_TIMEOUT })
    .then(
      async () =>
        ({
          kind: "error",
          log: (await bootError.textContent())?.trim() ?? "",
        }) as const,
    )
    .catch(() => ({ kind: "timeout" }) as const);
  return Promise.race([ready, failed]);
}

// ── App-level helpers ───────────────────────────────────────────────────────

/**
 * Make a fresh, empty backend project the current one. The backend keeps a
 * single global "current project", so tests must isolate themselves or they
 * inherit each other's image + layers.
 */
export async function freshProject(request: APIRequestContext, baseURL: string, name: string) {
  await expect
    .poll(
      async () => {
        const response = await request.post(`${baseURL}/api/projects`, { data: { name } });
        if (response.status() === 409) return false;
        expect(response.ok(), "create project").toBeTruthy();
        return true;
      },
      { timeout: 30_000, message: "wait for active worker before creating project" },
    )
    .toBeTruthy();
}

/** Load the app and wait for boot() to populate the backend badge. */
export async function gotoApp(page: Page) {
  let failures: BootRequestFailure[] = [];
  const onRequestFailed = (request: Request) => {
    failures.push({
      url: request.url(),
      error: request.failure()?.errorText ?? "unknown network failure",
    });
  };
  page.on("requestfailed", onRequestFailed);

  try {
    for (let attempt = 1; attempt <= 2; attempt += 1) {
      failures = [];
      const outcome = await runBootAttempt(page, () =>
        attempt === 1
          ? page.goto("/", { timeout: BOOT_ATTEMPT_TIMEOUT })
          : page.reload({ timeout: BOOT_ATTEMPT_TIMEOUT }),
      );
      if (outcome.kind === "ready") {
        await expect(page.locator(".status .badge")).not.toContainText("…", {
          timeout: 10_000,
        });
        return;
      }

      const visibleLog =
        (
          await page
            .locator(".status .log")
            .textContent()
            .catch(() => "")
        )?.trim() ?? "";
      const log =
        outcome.kind === "error" || outcome.kind === "navigation-error"
          ? outcome.log
          : visibleLog;
      if (attempt < 2 && isTransientBootFailure(log, failures)) {
        console.warn(
          `[e2e] transient boot fetch failed; reloading once (${failures.map((failure) => `${failure.url}: ${failure.error}`).join(", ")})`,
        );
        await page.waitForTimeout(250);
        continue;
      }

      const detail = failures.length
        ? failures
            .map((failure) => `${failure.url}: ${failure.error}`)
            .join(", ")
        : "no failed requests observed";
      throw new Error(
        `gotoApp boot attempt ${attempt} failed (${outcome.kind}; ${log || "no boot error"}; ${detail})`,
      );
    }
  } finally {
    page.off("requestfailed", onRequestFailed);
  }
}

/** Wait for the boot() sequence (its trailing GET /api/versions) to settle. */
export async function waitForBoot(page: Page) {
  await page.waitForResponse(
    (r) => r.url().includes("/api/versions") && r.request().method() === "GET",
    { timeout: 20_000 },
  );
}

/** Read the current backend composition. */
export async function getComposition(request: APIRequestContext, baseURL: string): Promise<CompositionT> {
  const response = await request.get(`${baseURL}/api/composition`);
  expect(response.ok(), "read composition").toBeTruthy();
  const json = await response.json();
  return json.composition;
}

/** Poll the backend composition until it meets a caller-provided condition. */
export async function waitForComposition(
  request: APIRequestContext,
  baseURL: string,
  predicate: (composition: CompositionT) => boolean,
  message: string,
  timeout = 20_000,
) {
  let latest: CompositionT | undefined;
  await expect
    .poll(
      async () => {
        latest = await getComposition(request, baseURL);
        return predicate(latest);
      },
      { timeout, message },
    )
    .toBeTruthy();
  return latest!;
}

/** Wait until any composition layer contains generated drawing geometry. */
export async function waitForGeneratedLayer(
  request: APIRequestContext,
  baseURL: string,
  timeout = 60_000,
) {
  return waitForComposition(
    request,
    baseURL,
    (composition) => composition.layers.some((layer) => DRAWING_SHAPE.test(layer.svg ?? "")),
    "wait for generated layer geometry",
    timeout,
  );
}

/** Import a raster/SVG via the hidden file input (same input the menu/rail use). */
export async function importImage(page: Page, file: string) {
  await page.locator('input[type="file"]').setInputFiles(file);
  // Run-path-finding enables once studio.imageUrl is set.
  await expect(page.locator('button[title="Run path finding"]')).toBeEnabled({ timeout: 15_000 });
}

/** Run the single-PFM "Run path finding" flow and wait for the SSE result. */
export async function runPathFinding(page: Page) {
  await page.locator('button[title="Run path finding"]').click();
  await waitForReady(page);
}

/** Wait for the StatusBar to report a finished run. */
export async function waitForReady(page: Page) {
  await expect(page.locator(".status .state")).toHaveText("Ready", { timeout: 60_000 });
}

/** Click a workflow step tab by its label (Path Finding / Generate / Composition / Plot). */
export async function gotoStep(page: Page, label: string) {
  await page.getByRole("tab", { name: label }).click();
}

/** Reveal a generator param group by clicking its tab in the Generate panel. */
export async function gotoGenGroup(page: Page, name: string) {
  await page.locator(".tabs button", { hasText: name }).click();
}

// ── Perf recorder fixture ────────────────────────────────────────────────────

export type PerfRecord = { story: string; pfm?: string; duration_ms: number; shapes?: number };
export type RecordPerf = (rec: PerfRecord) => void;

export const test = base.extend<{ recordPerf: RecordPerf }>({
  recordPerf: async ({}, use) => {
    mkdirSync(dirname(PERF_FILE), { recursive: true });
    await use((rec) => appendFileSync(PERF_FILE, JSON.stringify({ ts: Date.now(), ...rec }) + "\n"));
  },
});

export { expect };
