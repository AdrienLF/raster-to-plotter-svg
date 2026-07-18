import { spawn, execSync, ChildProcess } from "child_process";
import { mkdtempSync } from "fs";
import { tmpdir } from "os";
import { dirname, join, resolve } from "path";
import { fileURLToPath } from "url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..");
const FRONTEND = resolve(HERE, "..");

let backend: ChildProcess | undefined;

async function waitForServer(url: string, timeoutMs = 60_000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    // If our backend already exited (e.g. "Address already in use"), fail now
    // rather than accepting a 200 from whatever else answers on this port.
    if (backend && backend.exitCode !== null) {
      throw new Error(
        `Backend exited with code ${backend.exitCode} before serving. ` +
          `See its output above (a stale server on the same port is the usual cause).`,
      );
    }
    try {
      const r = await fetch(url);
      if (r.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`Backend did not come up at ${url} within ${timeoutMs}ms`);
}

/** Refuse to run against a server we did not start (orphan from a previous run). */
async function assertPortFree(url: string) {
  try {
    await fetch(url);
  } catch {
    return; // connection refused → port free
  }
  throw new Error(
    `Something is already listening at ${url}. The suite would silently test ` +
      `that (stale) server instead of this checkout. Kill it or set E2E_PORT ` +
      `to a free port, then re-run.`,
  );
}

export default async function globalSetup() {
  const port = process.env.PLOTTER_PORT || "7440";
  await assertPortFree(`http://127.0.0.1:${port}/`);

  // Build the SPA so Flask serves the current code (skip with E2E_SKIP_BUILD=1).
  if (!process.env.E2E_SKIP_BUILD) {
    execSync("npm run build", { cwd: FRONTEND, stdio: "inherit" });
  }

  // Isolated HOME so the backend's ~/.plotterforge, ~/.plotter_settings.json,
  // resume-job and paths-cache files never touch the real user profile.
  const home = mkdtempSync(join(tmpdir(), "plotter-e2e-"));
  // Isolated, locked, runtime-only environment: Playwright cannot inherit or
  // mutate the project's .venv, CUDA, MPS, or SAM2.
  const cmd =
    process.env.E2E_BACKEND_CMD ||
    "uv run --isolated --locked --no-dev python -m web.server";

  backend = spawn(cmd, {
    cwd: REPO,
    shell: true,
    // Own process group (POSIX) so teardown can kill the whole tree: `uv run`
    // execs python as a child, and SIGTERM to the shell/uv alone orphans the
    // server, which then squats on the port for every later run.
    detached: process.platform !== "win32",
    stdio: "inherit",
    env: {
      ...process.env,
      HOME: home,
      USERPROFILE: home, // Path.home() uses USERPROFILE on Windows
      PLOTTER_PORT: port,
      PLOTTER_HOST: "127.0.0.1",
      PLOTTER_FAKE_SERIAL: "1",
      SAM2_AUTO_SETUP: "0",
      PLOTTER_LOG_FILE: "0",
    },
  });

  console.log(`[e2e] backend pid=${backend.pid} home=${home} port=${port}`);
  await waitForServer(`http://127.0.0.1:${port}/`);

  // Returned function runs as global teardown.
  return async () => {
    if (backend && backend.pid) {
      if (process.platform === "win32") {
        try {
          execSync(`taskkill /pid ${backend.pid} /T /F`, { stdio: "ignore" });
        } catch {
          /* already gone */
        }
      } else {
        try {
          process.kill(-backend.pid, "SIGTERM"); // whole process group
        } catch {
          backend.kill("SIGTERM"); // group already gone — best effort
        }
      }
    }
  };
}
