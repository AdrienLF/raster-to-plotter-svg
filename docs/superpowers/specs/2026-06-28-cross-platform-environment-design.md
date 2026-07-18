# Cross-Platform Python, GPU, and SAM2 Environment Design

**Status:** Approved design

## Purpose

Make PlotterForge reproducible on Windows with NVIDIA CUDA and on macOS with
Metal/MPS. `uv` is the only Python environment manager. SAM2 is an essential,
verified part of a full installation, while application launch remains fast and
never mutates dependencies.

## Current problems

- The shell can expose Conda Python 3.11 while the project `.venv` uses uv-managed
  Python 3.13.2.
- The README requires Python 3.14+, while `pyproject.toml` and `.python-version`
  use Python 3.13.
- `uv run` performs an inexact sync by default. Commands that omit the GPU extra
  can therefore inherit Torch from an earlier GPU sync, making the selected
  backend depend on environment history.
- The `gpu` extra always selects CUDA 12.4 wheels, including on macOS where those
  wheels do not exist and MPS should use the macOS PyPI build.
- SAM2 is not locked. Runtime installation can replace the working CUDA Torch
  build, and an exact sync can later remove SAM2.
- The Windows and macOS launchers sync dependencies, build the frontend, and kill
  any process listening on the application port every time they launch.
- `web/requirements.txt` duplicates a stale subset of `pyproject.toml`.
- E2E currently starts its backend in the application `.venv`, so test behavior
  can inherit or alter GPU and SAM2 packages.

## Design principles

1. One dependency manifest and one universal uv lockfile.
2. Explicit platform accelerator profiles: CUDA on Windows, MPS on macOS.
3. SAM2 is pinned, installed, and verified during full setup.
4. Setup mutates dependencies; launch never does.
5. Conda is neither required nor consulted.
6. Tests cannot mutate or inherit the application environment.
7. A setup is successful only when its real hardware/backend smoke checks pass.

## Dependency model

`pyproject.toml` remains the single Python dependency source. Python support is
aligned on the 3.13 series in `requires-python`, `.python-version`, documentation,
and diagnostics.

Optional dependency profiles are separated by responsibility:

- `cuda`: matching Torch and Torchvision builds from an explicit PyTorch CUDA
  index, available only on Windows.
- `mps`: matching Torch and Torchvision macOS builds from PyPI, available only on
  macOS.
- `sam2`: SAM2 from an immutable upstream revision plus its required dependencies.

The CUDA and MPS profiles conflict so one environment cannot resolve both.
Platform and extra markers select the correct Torch source. The SAM2 revision is
recorded in `uv.lock`; runtime package installation is removed.

`web/requirements.txt` is deleted. Development and test dependencies remain in
uv dependency groups rather than a second requirements format.

## SAM2 strategy

SAM2 is essential to the supported full product. Both platform setup scripts
install the `sam2` profile and download the default configured checkpoint before
reporting success.

The optional SAM2 CUDA extension is disabled by default during installation.
Core SAM2 inference still uses CUDA or MPS through PyTorch; disabling the
extension avoids coupling installation to the host CUDA compiler and preserves
the supported segmentation result, with only optional mask post-processing
omitted. A future explicit advanced setup may enable the extension after testing
a matching compiler/toolkit stack, but it is outside this cleanup.

The application may boot far enough to show a setup diagnostic when SAM2 is
missing, but the condition is reported as **setup incomplete**, not as a normal
optional-feature state. The server never invokes pip or uv.

## Platform setup

### Windows

`setup-windows.bat`:

1. Clears inherited Conda variables for its child processes.
2. Verifies `uv`, Node.js, and npm are available.
3. Uses uv to install/select Python 3.13.
4. Performs an exact locked sync with `cuda` and `sam2`.
5. Uses `npm ci` and builds the frontend.
6. Downloads the configured default SAM2 checkpoint explicitly.
7. Runs the environment diagnostic and a minimal SAM2 inference smoke test.

The diagnostic requires the uv-managed interpreter, matching Torch/Torchvision,
CUDA availability, the expected CUDA Torch build, an NVIDIA device, SAM2 import,
checkpoint readability, and successful inference.

### macOS

`setup-macos.command` follows the same flow with `mps` and `sam2`. Its diagnostic
requires the uv-managed interpreter, matching Torch/Torchvision, MPS availability,
SAM2 import, checkpoint readability, and successful inference.

The lockfile and platform markers are validated on Windows. The final hardware
smoke test must also be executed on an MPS-capable Mac before macOS support is
claimed complete.

## Launch behavior

`start-windows.bat` and `start-macos.command`:

- clear inherited Conda variables for child processes;
- verify the prepared `.venv` and lockfile state without syncing;
- run the environment diagnostic in quick mode;
- fail with an actionable setup command if the environment is absent or stale;
- fail clearly if port 7438 is occupied;
- launch the server with the uv-managed interpreter.

They do not install Python packages, run npm, rebuild assets, download models, or
terminate unrelated processes. Dependency or frontend changes require rerunning
the platform setup script explicitly.

## Conda isolation

The project does not uninstall a user's global Miniconda installation. Instead,
it removes Conda from the project execution path:

- no repository command or document instructs users to run Conda;
- scripts never resolve bare `python` or `pip` from `PATH`;
- inherited `CONDA_*` variables are cleared for setup and launch child processes;
- diagnostics reject interpreters or imported packages located under a Conda
  prefix;
- the uv-managed `.venv` is the only supported application environment.

This makes behavior identical whether setup is invoked from a normal shell or a
shell where Conda `base` was previously active.

## Diagnostics and errors

A small Python environment diagnostic is the shared source of truth for setup,
launch, support, and automated tests. It reports:

- interpreter executable and Python version;
- whether any interpreter/package path comes from Conda;
- Torch, Torchvision, and SAM2 versions;
- selected accelerator and device;
- Torch CUDA runtime on Windows or MPS availability on macOS;
- checkpoint path and readability;
- concise corrective commands for every failure.

Setup exits non-zero on any failed required check. Launch exits non-zero for a
missing/stale environment or occupied port. The application status endpoint and
UI surface the same setup-incomplete reason without attempting self-repair.

## Test isolation

Backend unit tests and Playwright use isolated uv environments, not the
application `.venv`. The E2E backend runs the locked base dependency set without
CUDA, MPS, or SAM2 and continues to set `SAM2_AUTO_SETUP=0`. This makes browser
tests deterministic and prevents them from installing, removing, or inheriting
application packages.

Automated coverage includes:

- dependency-contract tests for platform markers, extras, conflicts, and the
  pinned SAM2 source;
- launcher-contract tests proving setup and launch responsibilities stay separate;
- diagnostic unit tests for Conda contamination, wrong Python, CPU-only Torch,
  mismatched Torch/Torchvision, missing SAM2, missing checkpoints, and healthy
  CUDA/MPS reports;
- existing backend, frontend, and Playwright suites;
- Windows CUDA/SAM2 setup and inference smoke verification;
- macOS lock/platform validation, followed by a real MPS/SAM2 smoke run on Mac.

## Delivery sequence

1. Finish the existing E2E stabilization plan on `e2e-playwright-harness`.
2. Require backend tests, frontend check/build, and two consecutive green full
   Playwright runs.
3. Merge the verified E2E branch into `main` and push `main`.
4. Create a fresh environment-cleanup branch from updated `main`.
5. Implement this design test-first, one environment boundary at a time.
6. Verify Windows locally and record the remaining Mac hardware verification as
   a release gate until it is run on the target Mac.

## Acceptance criteria

- Windows full setup produces Python 3.13, CUDA Torch, importable SAM2, the default
  checkpoint, and a successful GPU inference smoke test.
- macOS full setup produces Python 3.13, MPS Torch, importable SAM2, the default
  checkpoint, and a successful MPS inference smoke test on target hardware.
- Running from an active Conda shell does not select a Conda interpreter or
  Conda-installed package.
- Launch makes no network request and performs no install, sync, build, download,
  or process termination.
- `pyproject.toml` and `uv.lock` are the only Python dependency definitions.
- Tests do not change the application `.venv`.
- Missing or broken SAM2 is reported as setup incomplete with a precise recovery
  command.
