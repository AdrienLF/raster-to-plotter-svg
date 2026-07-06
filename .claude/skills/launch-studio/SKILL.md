---
name: launch-studio
description: Launch Plotter Studio (this repo's Svelte + Flask web app) for local use or to verify a change. Use whenever the user asks to run, start, launch, or open the app/studio/server in this project.
---

# Launch Plotter Studio

Plotter Studio is the web app in this repo: `engine/` (conversion engine) +
`frontend/` (Svelte 5 SPA) + `web/server.py` (Flask API + plotter driver). It
serves on **http://localhost:7438**.

## Steps

1. **Check the environment is prepared.** `.venv/bin/python` must exist and be
   executable.
   - Missing → run `./setup-macos.command` (macOS) or `setup-windows.bat`
     (Windows) first. This is the *setup* step (installs Torch, SAM2,
     checkpoint, frontend deps) and is slow; don't run it speculatively —
     only if the launch step below reports it's missing.

2. **Check port 7438 is free:**
   ```sh
   lsof -nP -iTCP:7438 -sTCP:LISTEN -t
   ```
   - If a PID is returned, a studio may already be running — check with the
     user before killing it; don't assume it's stale.

3. **Launch (offline, no installs/builds):**
   ```sh
   ./start-studio.command   # macOS
   start-studio.bat         # Windows
   ```
   This runs `uv run --locked --no-sync python -m web.server` after an
   environment check (`web.env_check --backend mps`). Run it with
   `run_in_background: true` — it's a long-running server, not a one-shot
   command.

4. **Open http://localhost:7438** in a browser to confirm it's up (e.g.
   `open http://localhost:7438` on macOS) once the log shows the server
   started.

## Frontend-only dev loop (hot reload)

If iterating on `frontend/` UI code specifically, prefer:
```sh
cd frontend && npm run dev
```
This proxies `/api` to the Flask server, so the Flask server (step 3) must
already be running.

## Recovery (from README.md, keep in sync with it)

- **`Run ./setup-macos.command first.`** → `.venv` missing/stale, rerun setup.
- **`Port 7438 is already in use by PID …`** → another studio is running;
  launchers never kill the port owner, so stop that PID manually and retry.
- **CUDA/MPS unavailable** → `web.env_check` reports it; check GPU
  driver/hardware, then rerun setup.
- **`Plotter Studio setup is incomplete: missing …`** → SAM2/Torch/checkpoint
  absent at runtime; rerun setup (the server itself never installs anything).

## Legacy GUI (not the web app)

`uv run python main.py` launches the older customtkinter desktop GUI
(`stipple.py` / `svg_export.py`). Only use this if the user explicitly asks
for the legacy GUI rather than Plotter Studio.
