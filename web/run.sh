#!/bin/sh
# Generic prepared-environment launcher. Run from the repo root so `engine` and
# `web` import cleanly. It does not choose an accelerator profile or sync — run
# the platform setup script first. Offline: never installs, builds, or kills.
cd "$(dirname "$0")/.."
if [ ! -d ".venv" ]; then
  echo "Run the platform setup script first (setup-windows.bat / ./setup-macos.command)." >&2
  exit 1
fi
exec uv run --locked --no-sync python -m web.server
