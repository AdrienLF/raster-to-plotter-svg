#!/bin/sh
# Plotter Studio — one-click launch (Metal/MPS).
# Double-click in Finder, or run: ./start-studio.command
#
# Offline launcher: it never installs, syncs, builds, downloads, or kills
# processes. Run ./setup-macos.command first to prepare the environment.

cd "$(dirname "$0")" || exit 1
PORT=7438

unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_PROMPT_MODIFIER CONDA_PYTHON_EXE CONDA_SHLVL

if [ ! -x ".venv/bin/python" ]; then
  echo "Run ./setup-macos.command first." >&2
  exit 1
fi

PIDS=$(lsof -nP -iTCP:$PORT -sTCP:LISTEN -t 2>/dev/null)
if [ -n "$PIDS" ]; then
  echo "Port $PORT is already in use by PID $PIDS. Stop it and retry." >&2
  exit 1
fi

echo "▸ Verifying environment…"
uv run --locked --no-sync python -m web.env_check --backend mps || exit 1

echo ""
echo "▸ Starting Plotter Studio (MPS)…"
echo "    Local:  http://localhost:$PORT"
echo "  (Press Ctrl+C to stop.)"
echo ""

exec uv run --locked --no-sync python -m web.server
