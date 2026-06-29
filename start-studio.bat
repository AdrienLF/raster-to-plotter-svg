@echo off
setlocal
cd /d "%~dp0"
set PORT=7438

set "CONDA_PREFIX="
set "CONDA_DEFAULT_ENV="
set "CONDA_PROMPT_MODIFIER="
set "CONDA_PYTHON_EXE="
set "CONDA_SHLVL="

if not exist ".venv\Scripts\python.exe" (
    echo Run setup-windows.bat first.
    exit /b 1
)

for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    echo Port %PORT% is already in use by PID %%p. Stop it and retry.
    exit /b 1
)

echo . Verifying environment...
uv run --locked --no-sync python -m web.env_check --backend cuda || exit /b 1

echo.
echo . Starting Plotter Studio (CUDA)...
echo     Local:  http://localhost:%PORT%
echo   (Press Ctrl+C to stop.)
echo.

uv run --locked --no-sync python -m web.server
