# Cross-Platform Environment Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stateful uv/Conda/CUDA/SAM2 setup with one locked Python 3.13 project, explicit Windows CUDA and macOS MPS setup profiles, first-class SAM2 verification, mutation-free launchers, and isolated test environments.

**Architecture:** `pyproject.toml` and `uv.lock` are the only Python dependency definitions. Platform setup scripts perform exact locked syncs with `cuda + sam2` or `mps + sam2`; launch scripts only validate and start the prepared environment. A shared Python diagnostic verifies interpreter provenance, accelerator selection, SAM2, checkpoints, and smoke inference, while E2E runs in an isolated base environment.

**Tech Stack:** Python 3.13, uv, PyTorch/Torchvision, CUDA, Metal/MPS, SAM2, Flask, unittest/pytest, PowerShell/batch, POSIX shell, npm/Vite, Playwright.

---

## Prerequisite and scope

Before starting Task 1, complete `docs/superpowers/plans/2026-06-27-e2e-branch-stabilization.md`, obtain two consecutive green full Playwright runs, merge `e2e-playwright-harness` into `main`, push `main`, and create `codex/clean-cross-platform-environment` from updated `main`.

This plan covers only environment cleanup. It does not duplicate E2E selector/race stabilization, enable SAM2's optional custom CUDA extension, uninstall Miniconda globally, or claim macOS hardware verification from a Windows machine.

## File map

- `pyproject.toml` — Python 3.13 range, platform accelerator extras, SAM2 extra, source markers, conflicts, and build-isolation policy.
- `.python-version` — canonical uv-managed Python series.
- `uv.lock` — universal locked dependency graph including immutable SAM2 revision.
- `web/requirements.txt` — delete the stale duplicate dependency list.
- `web/env_check.py` — shared environment inspection, checkpoint preparation, and optional inference smoke CLI.
- `tests/test_env_check.py` — unit coverage for diagnostic decisions and messages.
- `tests/test_environment_contracts.py` — manifest, script, Conda-isolation, and E2E-isolation source contracts.
- `web/server.py` — remove runtime package installation and report setup-incomplete states.
- `tests/test_regions.py` — replace runtime-install tests with setup-incomplete and explicit-download behavior.
- `setup-windows.bat` — exact Windows CUDA + SAM2 setup and verification.
- `setup-macos.command` — exact macOS MPS + SAM2 setup and verification.
- `start-windows.bat` — mutation-free Windows launch.
- `start-macos.command` — mutation-free macOS launch.
- `web/run.sh` — mutation-free command-line launch wrapper.
- `frontend/e2e/global-setup.ts` — isolated uv backend command.
- `frontend/e2e/README.md` — deterministic test environment documentation.
- `README.md` — platform setup, launch, requirements, SAM2, Conda, and recovery documentation.

### Task 1: Lock the platform dependency model

**Files:**
- Create: `tests/test_environment_contracts.py`
- Modify: `pyproject.toml`
- Modify: `.python-version`
- Modify: `uv.lock`
- Delete: `web/requirements.txt`

- [ ] **Step 1: Write failing dependency-contract tests**

Create `tests/test_environment_contracts.py` with these initial tests:

```python
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAM2_REVISION = "2b90b9f5ceec907a1c18123530e92e794ad901a4"


class DependencyContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def test_python_is_pinned_to_the_313_series(self):
        self.assertEqual(self.project["project"]["requires-python"], ">=3.13,<3.14")
        self.assertEqual((ROOT / ".python-version").read_text().strip(), "3.13")

    def test_accelerator_and_sam2_extras_are_explicit(self):
        extras = self.project["project"]["optional-dependencies"]
        self.assertEqual(extras["cuda"], ["torch>=2.6,<2.7", "torchvision>=0.21,<0.22"])
        self.assertEqual(extras["mps"], ["torch>=2.6,<2.7", "torchvision>=0.21,<0.22"])
        self.assertIn("sam-2", extras["sam2"])
        self.assertIn("setuptools>=61", extras["sam2"])

    def test_cuda_and_mps_profiles_conflict(self):
        conflicts = self.project["tool"]["uv"]["conflicts"]
        self.assertIn([{"extra": "cuda"}, {"extra": "mps"}], conflicts)

    def test_cuda_torch_sources_are_windows_only(self):
        sources = self.project["tool"]["uv"]["sources"]
        for package in ("torch", "torchvision"):
            self.assertEqual(sources[package], [{
                "index": "pytorch-cu124",
                "extra": "cuda",
                "marker": "sys_platform == 'win32'",
            }])

    def test_sam2_source_is_immutable_and_not_build_isolated(self):
        uv = self.project["tool"]["uv"]
        self.assertEqual(uv["sources"]["sam-2"], {
            "git": "https://github.com/facebookresearch/sam2.git",
            "rev": SAM2_REVISION,
        })
        self.assertIn("sam-2", uv["no-build-isolation-package"])

    def test_no_second_python_dependency_manifest_exists(self):
        self.assertFalse((ROOT / "web" / "requirements.txt").exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the contracts and verify RED**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_environment_contracts.py -q
```

Expected: failures for the Python range, missing `cuda`/`mps`/`sam2` extras, missing conflicts/source pin, and existing `web/requirements.txt`.

- [ ] **Step 3: Replace the dependency configuration**

Update `pyproject.toml` so the relevant sections are exactly:

```toml
[project]
name = "plotterforge"
version = "0.1.0"
description = "Convert a raster image to a plotter-ready SVG of stippled dots"
requires-python = ">=3.13,<3.14"
dependencies = [
    "customtkinter>=5.2.2",
    "numpy>=2.4.6",
    "pillow>=12.2.0",
    "svgwrite>=1.4.3",
    "flask>=3.0",
    "pyserial>=3.5",
    "svgelements>=1.8",
    "scipy>=1.13",
    "scikit-image>=0.24",
    "opencv-python-headless>=4.10",
]

[project.optional-dependencies]
cuda = [
    "torch>=2.6,<2.7",
    "torchvision>=0.21,<0.22",
]
mps = [
    "torch>=2.6,<2.7",
    "torchvision>=0.21,<0.22",
]
sam2 = [
    "sam-2",
    "setuptools>=61",
]

[dependency-groups]
dev = [
    "pytest>=8",
]

[tool.uv]
conflicts = [
    [
        { extra = "cuda" },
        { extra = "mps" },
    ],
]
no-build-isolation-package = ["sam-2"]

[tool.uv.sources]
torch = [
    { index = "pytorch-cu124", extra = "cuda", marker = "sys_platform == 'win32'" },
]
torchvision = [
    { index = "pytorch-cu124", extra = "cuda", marker = "sys_platform == 'win32'" },
]
sam-2 = { git = "https://github.com/facebookresearch/sam2.git", rev = "2b90b9f5ceec907a1c18123530e92e794ad901a4" }

[[tool.uv.index]]
name = "pytorch-cu124"
url = "https://download.pytorch.org/whl/cu124"
explicit = true
```

Keep `.python-version` as `3.13`, and delete `web/requirements.txt`.

- [ ] **Step 4: Regenerate and validate the universal lock**

Run:

```powershell
$env:SAM2_BUILD_CUDA = "0"
uv lock
uv lock --check
uv sync --dry-run --locked --extra cuda --extra sam2
Remove-Item Env:SAM2_BUILD_CUDA
```

Expected: lock succeeds; the Windows dry run selects `torch==2.6.0+cu124`, matching Torchvision, and the pinned SAM2 Git revision. It must not select a second CPU Torch build.

Then validate that the universal lock contains the macOS branch without trying
to emulate macOS installation on Windows:

```powershell
uv lock --check
Select-String -Path uv.lock -Pattern "sys_platform == 'darwin'","extra == 'mps'" -Context 0,2
```

Expected: the lock is current and contains the Darwin/MPS dependency branch.
Actual installation and MPS device availability remain the target-Mac release
gate in Task 10.

- [ ] **Step 5: Run the contracts and verify GREEN**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_environment_contracts.py -q
```

Expected: all dependency contracts pass.

- [ ] **Step 6: Commit the dependency model**

```powershell
git add pyproject.toml .python-version uv.lock tests/test_environment_contracts.py web/requirements.txt
git commit -m "build: lock platform GPU and SAM2 profiles"
```

### Task 2: Add the shared environment diagnostic

**Files:**
- Create: `web/env_check.py`
- Create: `tests/test_env_check.py`

- [ ] **Step 1: Write failing diagnostic unit tests**

Create `tests/test_env_check.py`:

```python
import unittest
from pathlib import Path
from unittest import mock

from web import env_check


class EnvironmentCheckTest(unittest.TestCase):
    def test_conda_interpreter_is_rejected(self):
        errors = env_check.conda_errors(
            executable=Path("C:/Users/A/miniconda3/python.exe"),
            base_prefix=Path("C:/Users/A/miniconda3"),
            module_paths=[],
            environ={},
        )
        self.assertIn("Conda interpreter detected", errors[0])

    def test_conda_package_path_is_rejected(self):
        errors = env_check.conda_errors(
            executable=Path("C:/repo/.venv/Scripts/python.exe"),
            base_prefix=Path("C:/uv/python/3.13"),
            module_paths=[Path("C:/Users/A/miniconda3/Lib/site-packages/torch/__init__.py")],
            environ={},
        )
        self.assertTrue(any("Conda package path" in error for error in errors))

    def test_cuda_backend_requires_cuda_and_reports_device(self):
        torch = mock.Mock()
        torch.__version__ = "2.6.0+cu124"
        torch.version.cuda = "12.4"
        torch.cuda.is_available.return_value = True
        torch.cuda.get_device_name.return_value = "NVIDIA GeForce RTX 3090"

        details, errors = env_check.accelerator_status(torch, "cuda")

        self.assertEqual(errors, [])
        self.assertEqual(details["device"], "NVIDIA GeForce RTX 3090")
        self.assertEqual(details["torch_cuda"], "12.4")

    def test_mps_backend_requires_mps(self):
        torch = mock.Mock()
        torch.__version__ = "2.6.0"
        torch.backends.mps.is_available.return_value = False

        _, errors = env_check.accelerator_status(torch, "mps")

        self.assertEqual(errors, ["MPS is not available to PyTorch"])

    def test_wrong_python_series_is_rejected(self):
        self.assertEqual(
            env_check.python_errors((3, 12, 9)),
            ["Python 3.13 is required; found 3.12.9"],
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the diagnostic tests and verify RED**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_env_check.py -q
```

Expected: import failure because `web.env_check` does not exist.

- [ ] **Step 3: Implement the pure diagnostic helpers and CLI shell**

Create `web/env_check.py` with these public units:

```python
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _looks_like_conda(path: Path) -> bool:
    value = str(path).lower().replace("\\", "/")
    return any(part in value for part in ("/miniconda", "/anaconda", "/conda/"))


def python_errors(version: tuple[int, int, int]) -> list[str]:
    if version[:2] == (3, 13):
        return []
    found = ".".join(map(str, version))
    return [f"Python 3.13 is required; found {found}"]


def conda_errors(
    *,
    executable: Path,
    base_prefix: Path,
    module_paths: list[Path],
    environ: dict[str, str],
) -> list[str]:
    errors = []
    if _looks_like_conda(executable) or _looks_like_conda(base_prefix):
        errors.append(f"Conda interpreter detected: {executable}")
    for path in module_paths:
        if _looks_like_conda(path):
            errors.append(f"Conda package path detected: {path}")
    if environ.get("CONDA_PREFIX") and _looks_like_conda(Path(environ["CONDA_PREFIX"])):
        errors.append("Active CONDA_PREFIX leaked into the project process")
    return errors


def accelerator_status(torch, expected: str) -> tuple[dict[str, str], list[str]]:
    details = {"torch": str(torch.__version__)}
    if expected == "cuda":
        if not torch.cuda.is_available():
            return details, ["CUDA is not available to PyTorch"]
        details["torch_cuda"] = str(torch.version.cuda)
        details["device"] = str(torch.cuda.get_device_name(0))
        return details, []
    if expected == "mps":
        if not torch.backends.mps.is_available():
            return details, ["MPS is not available to PyTorch"]
        details["device"] = "mps"
        return details, []
    return details, [f"Unsupported expected backend: {expected}"]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Validate the PlotterForge environment")
    parser.add_argument("--backend", required=True, choices=("cuda", "mps"))
    parser.add_argument("--checkpoint")
    parser.add_argument("--download-checkpoint", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)
```

Add `main()` after the helpers. It must import Torch, Torchvision, and SAM2 lazily; collect their `__file__` paths; run `python_errors`, `conda_errors`, and `accelerator_status`; print every error to stderr; and exit 1 if any required check fails. It must print a JSON object when `--json` is passed and human-readable `key: value` lines otherwise.

Do not implement checkpoint download or smoke inference in this step; `--download-checkpoint` and `--smoke` must return an explicit `not implemented` error so the next task begins RED.

- [ ] **Step 4: Run the tests and verify GREEN**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_env_check.py -q
```

Expected: all five tests pass.

- [ ] **Step 5: Commit the base diagnostic**

```powershell
git add web/env_check.py tests/test_env_check.py
git commit -m "feat: diagnose managed Python and GPU backend"
```

### Task 3: Add checkpoint preparation and real SAM2 smoke inference

**Files:**
- Modify: `web/env_check.py`
- Modify: `tests/test_env_check.py`

- [ ] **Step 1: Add failing tests for checkpoint preparation and smoke dispatch**

Append tests that inject download and smoke functions instead of loading the real model:

```python
    def test_prepare_checkpoint_downloads_only_when_requested(self):
        target = Path("C:/models/sam2.1_hiera_tiny.pt")
        download = mock.Mock()

        result = env_check.prepare_checkpoint(
            target,
            "https://example.test/model.pt",
            allow_download=True,
            downloader=download,
        )

        self.assertEqual(result, target)
        download.assert_called_once_with("https://example.test/model.pt", target)

    def test_missing_checkpoint_without_download_is_an_error(self):
        with self.assertRaisesRegex(RuntimeError, "checkpoint is missing"):
            env_check.prepare_checkpoint(
                Path("C:/models/missing.pt"),
                "https://example.test/model.pt",
                allow_download=False,
                downloader=mock.Mock(),
            )

    def test_smoke_inference_requires_a_nonempty_mask(self):
        predictor = mock.Mock()
        predictor.predict.return_value = (mock.Mock(size=0), [], None)

        with self.assertRaisesRegex(RuntimeError, "no masks"):
            env_check.run_predictor_smoke(predictor, mock.Mock(), mock.Mock())
```

Use `tempfile.TemporaryDirectory()` for the first two tests in the real file so Windows paths are not created.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_env_check.py -q
```

Expected: failures because `prepare_checkpoint` and `run_predictor_smoke` do not exist.

- [ ] **Step 3: Implement explicit checkpoint preparation**

Implement:

```python
DEFAULT_MODEL = "sam2.1_hiera_tiny"
DEFAULT_CONFIG = "configs/sam2.1/sam2.1_hiera_t.yaml"
DEFAULT_CHECKPOINT_URL = (
    "https://dl.fbaipublicfiles.com/segment_anything_2/092824/"
    "sam2.1_hiera_tiny.pt"
)


def download_file(url: str, target: Path) -> None:
    import urllib.request

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    urllib.request.urlretrieve(url, partial)
    partial.replace(target)


def prepare_checkpoint(
    target: Path,
    url: str,
    *,
    allow_download: bool,
    downloader=download_file,
) -> Path:
    if target.is_file():
        return target
    if not allow_download:
        raise RuntimeError(f"SAM2 checkpoint is missing: {target}")
    downloader(url, target)
    if not target.is_file():
        raise RuntimeError(f"SAM2 checkpoint download did not create: {target}")
    return target
```

- [ ] **Step 4: Implement real smoke inference**

Implement `run_predictor_smoke(predictor, np, torch)` using a 32×32 black RGB image and one positive point at `(16, 16)`. Call `predictor.set_image`, then `predict(..., multimask_output=False)` under `torch.inference_mode()`. Raise `RuntimeError("SAM2 smoke inference returned no masks")` when no mask is returned.

In `main()`, when `--smoke` is set:

1. Resolve the checkpoint from `--checkpoint`, `SAM2_CHECKPOINT`, or `~/.plotterforge/models/sam2.1_hiera_tiny.pt`.
2. Call `prepare_checkpoint(..., allow_download=args.download_checkpoint)`.
3. Import `build_sam2` and `SAM2ImagePredictor`.
4. Build on the requested backend and run `run_predictor_smoke`.
5. Add `sam2_smoke: ok` to diagnostic details.

- [ ] **Step 5: Run unit tests and verify GREEN**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_env_check.py -q
```

Expected: all diagnostic tests pass without downloading a model.

- [ ] **Step 6: Commit explicit SAM2 preparation**

```powershell
git add web/env_check.py tests/test_env_check.py
git commit -m "feat: verify SAM2 checkpoint and inference"
```

### Task 4: Remove runtime dependency installation from the server

**Files:**
- Modify: `web/server.py:332-585`
- Modify: `tests/test_regions.py:370-470`

- [ ] **Step 1: Replace runtime-install tests with failing setup-incomplete tests**

Delete tests that expect `_install_sam2`, `auto_install`, or pip fallback. Add:

```python
    def test_missing_sam2_reports_platform_setup_command_without_installing(self):
        adapter = server.LocalSam2Adapter(checkpoint="missing.pt")

        with mock.patch.object(adapter, "_has_module", return_value=False):
            status = adapter.status()

        self.assertFalse(status["available"])
        self.assertEqual(status["setup_state"], "error")
        self.assertIn("setup-windows.bat", status["error"])
        self.assertNotIn("pip install", status["error"])

    def test_status_does_not_start_background_setup(self):
        adapter = server.LocalSam2Adapter(checkpoint="missing.pt")

        with mock.patch.object(adapter, "prepare_async") as prepare:
            adapter.status()

        prepare.assert_not_called()

    def test_server_source_contains_no_package_installer(self):
        source = (Path(server.__file__)).read_text(encoding="utf-8")
        self.assertNotIn("_install_sam2", source)
        self.assertNotIn("SAM2_AUTO_INSTALL", source)
        self.assertNotIn("'uv', 'pip', 'install'", source)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_regions.py -q
```

Expected: new assertions fail because status still starts background setup and installer code exists.

- [ ] **Step 3: Delete runtime package mutation**

In `LocalSam2Adapter`:

- remove `PACKAGE_URL`, `package_url`, `auto_install`, and `_install_sam2`;
- change missing-module handling to raise:

```python
raise RuntimeError(
    "PlotterForge setup is incomplete: missing "
    + ", ".join(missing_modules)
    + ". Run setup-windows.bat on Windows or ./setup-macos.command on macOS."
)
```

- make `status()` purely observational: do not call `prepare_async()`;
- report the same setup-incomplete error when modules or the checkpoint are missing;
- retain explicit checkpoint preparation only when a user selects a model or requests prediction;
- retain `SAM2_AUTO_SETUP=0` as a test/power-user switch for explicit checkpoint preparation, but never use it for package installation.

- [ ] **Step 4: Run region and event tests and verify GREEN**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_regions.py tests/test_event_stream.py -q
```

Expected: all focused tests pass and no subprocess package installation occurs.

- [ ] **Step 5: Commit the immutable runtime behavior**

```powershell
git add web/server.py tests/test_regions.py
git commit -m "fix: keep SAM2 installation out of runtime"
```

### Task 5: Add clean Windows and macOS setup scripts

**Files:**
- Create: `setup-windows.bat`
- Create: `setup-macos.command`
- Modify: `tests/test_environment_contracts.py`

- [ ] **Step 1: Add failing setup-script contracts**

Add tests:

```python
    def test_windows_setup_is_exact_locked_and_full(self):
        script = (ROOT / "setup-windows.bat").read_text(encoding="utf-8")
        self.assertIn("uv python install 3.13", script)
        self.assertIn("uv sync --locked --extra cuda --extra sam2", script)
        self.assertIn("set \"SAM2_BUILD_CUDA=0\"", script)
        self.assertIn("npm ci", script)
        self.assertIn("npm run build", script)
        self.assertIn("-m web.env_check --backend cuda --download-checkpoint --smoke", script)
        self.assertNotIn("conda ", script.lower())

    def test_macos_setup_is_exact_locked_and_full(self):
        script = (ROOT / "setup-macos.command").read_text(encoding="utf-8")
        self.assertIn("uv python install 3.13", script)
        self.assertIn("uv sync --locked --extra mps --extra sam2", script)
        self.assertIn("SAM2_BUILD_CUDA=0", script)
        self.assertIn("npm ci", script)
        self.assertIn("npm run build", script)
        self.assertIn("-m web.env_check --backend mps --download-checkpoint --smoke", script)
        self.assertNotIn("conda ", script.lower())
```

- [ ] **Step 2: Run contracts and verify RED**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_environment_contracts.py -q
```

Expected: file-not-found failures for both setup scripts.

- [ ] **Step 3: Implement `setup-windows.bat`**

The script must:

```bat
@echo off
setlocal
cd /d "%~dp0"

set "CONDA_PREFIX="
set "CONDA_DEFAULT_ENV="
set "CONDA_PROMPT_MODIFIER="
set "CONDA_PYTHON_EXE="
set "CONDA_SHLVL="
set "SAM2_BUILD_CUDA=0"

where uv >nul 2>&1 || (echo uv is required & exit /b 1)
where node >nul 2>&1 || (echo Node.js is required & exit /b 1)
where npm >nul 2>&1 || (echo npm is required & exit /b 1)

uv python install 3.13 || exit /b 1
uv sync --locked --extra cuda --extra sam2 || exit /b 1

pushd frontend
call npm ci || (popd & exit /b 1)
call npm run build || (popd & exit /b 1)
popd

uv run --locked --no-sync python -m web.env_check --backend cuda --download-checkpoint --smoke
exit /b %errorlevel%
```

Use the exact structure above; add concise progress labels but no port termination or server launch.

- [ ] **Step 4: Implement `setup-macos.command`**

Use a POSIX shell equivalent:

```sh
#!/bin/sh
set -eu
cd "$(dirname "$0")"

unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_PROMPT_MODIFIER CONDA_PYTHON_EXE CONDA_SHLVL
export SAM2_BUILD_CUDA=0

command -v uv >/dev/null || { echo "uv is required" >&2; exit 1; }
command -v node >/dev/null || { echo "Node.js is required" >&2; exit 1; }
command -v npm >/dev/null || { echo "npm is required" >&2; exit 1; }

uv python install 3.13
uv sync --locked --extra mps --extra sam2
(cd frontend && npm ci && npm run build)
uv run --locked --no-sync python -m web.env_check --backend mps --download-checkpoint --smoke
```

- [ ] **Step 5: Run contracts and verify GREEN**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_environment_contracts.py -q
```

Expected: setup-script contracts pass.

- [ ] **Step 6: Commit the setup scripts**

```powershell
git add setup-windows.bat setup-macos.command tests/test_environment_contracts.py
git commit -m "build: add full platform setup scripts"
```

### Task 6: Make every launcher mutation-free and Conda-independent

**Files:**
- Modify: `start-windows.bat`
- Modify: `start-macos.command`
- Modify: `web/run.sh`
- Modify: `tests/test_gpu_launch.py`
- Modify: `tests/test_environment_contracts.py`

- [ ] **Step 1: Replace old launch contracts with failing mutation-free contracts**

Replace `tests/test_gpu_launch.py` with assertions shared across the three launchers:

```python
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LaunchContractTest(unittest.TestCase):
    def test_launchers_never_install_build_download_or_kill(self):
        for relative in ("start-windows.bat", "start-macos.command", "web/run.sh"):
            source = (ROOT / relative).read_text(encoding="utf-8").lower()
            with self.subTest(relative=relative):
                for forbidden in (
                    "uv sync", "npm install", "npm ci", "npm run build",
                    "taskkill", "kill -9", "--download-checkpoint",
                ):
                    self.assertNotIn(forbidden, source)

    def test_platform_launchers_clear_conda_and_do_not_sync(self):
        windows = (ROOT / "start-windows.bat").read_text(encoding="utf-8")
        macos = (ROOT / "start-macos.command").read_text(encoding="utf-8")
        self.assertIn('set "CONDA_PREFIX="', windows)
        self.assertIn("unset CONDA_PREFIX", macos)
        self.assertIn("uv run --locked --no-sync", windows)
        self.assertIn("uv run --locked --no-sync", macos)

    def test_launchers_run_quick_environment_check(self):
        self.assertIn(
            "-m web.env_check --backend cuda",
            (ROOT / "start-windows.bat").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "-m web.env_check --backend mps",
            (ROOT / "start-macos.command").read_text(encoding="utf-8"),
        )
```

- [ ] **Step 2: Run launch contracts and verify RED**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_gpu_launch.py -q
```

Expected: failures because launchers currently sync, build, and kill port owners.

- [ ] **Step 3: Rewrite the Windows launcher**

`start-windows.bat` must clear Conda variables, require `.venv\Scripts\python.exe`, check port 7438 without terminating its owner, run the quick CUDA diagnostic, and launch:

```bat
uv run --locked --no-sync python -m web.env_check --backend cuda || exit /b 1
uv run --locked --no-sync python -m web.server
```

If `.venv` is absent, print `Run setup-windows.bat first.` If the port is occupied, print the owning PID and exit 1.

- [ ] **Step 4: Rewrite the macOS and shell launchers**

`start-macos.command` mirrors Windows with `--backend mps`, `lsof` for the non-destructive port check, and `exec uv run --locked --no-sync python -m web.server`.

`web/run.sh` is a generic prepared-environment wrapper. It must not choose an accelerator profile or sync; it runs `exec uv run --locked --no-sync python -m web.server` after checking `.venv` exists.

- [ ] **Step 5: Run launch contracts and verify GREEN**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_gpu_launch.py tests/test_environment_contracts.py -q
```

Expected: all launcher and environment contracts pass.

- [ ] **Step 6: Commit mutation-free launchers**

```powershell
git add start-windows.bat start-macos.command web/run.sh tests/test_gpu_launch.py tests/test_environment_contracts.py
git commit -m "fix: keep launchers out of dependency setup"
```

### Task 7: Isolate Playwright from the application environment

**Files:**
- Modify: `frontend/e2e/global-setup.ts:35-55`
- Modify: `frontend/e2e/README.md`
- Modify: `tests/test_environment_contracts.py`

- [ ] **Step 1: Add a failing E2E-isolation contract**

Add:

```python
    def test_e2e_backend_uses_an_isolated_locked_base_environment(self):
        setup = (ROOT / "frontend/e2e/global-setup.ts").read_text(encoding="utf-8")
        self.assertIn(
            '"uv run --isolated --locked --no-dev python -m web.server"',
            setup,
        )
        self.assertIn('SAM2_AUTO_SETUP: "0"', setup)
```

- [ ] **Step 2: Run the contract and verify RED**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_environment_contracts.py -q
```

Expected: failure because the current command is `uv run python -m web.server`.

- [ ] **Step 3: Change the isolated backend command**

In `frontend/e2e/global-setup.ts`, set:

```typescript
const cmd =
  process.env.E2E_BACKEND_CMD ||
  "uv run --isolated --locked --no-dev python -m web.server";
```

Keep the temporary HOME, fake serial, `SAM2_AUTO_SETUP=0`, port override, and process-tree teardown unchanged.

Document in `frontend/e2e/README.md` that Playwright creates an isolated uv environment containing only locked runtime dependencies, so it cannot inherit or mutate `.venv`, CUDA, MPS, or SAM2.

- [ ] **Step 4: Run contracts and a focused browser smoke**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_environment_contracts.py -q
Set-Location frontend
npx playwright test e2e/smoke.spec.ts --reporter=list
Set-Location ..
```

Expected: contracts pass and the smoke spec passes with the isolated backend.

- [ ] **Step 5: Commit test isolation**

```powershell
git add frontend/e2e/global-setup.ts frontend/e2e/README.md tests/test_environment_contracts.py
git commit -m "test: isolate Playwright from the app environment"
```

### Task 8: Rewrite setup and recovery documentation

**Files:**
- Modify: `README.md`
- Modify: `FEATURES.md`
- Test: `tests/test_environment_contracts.py`

- [ ] **Step 1: Add failing documentation contracts**

Add tests asserting that README contains `setup-windows.bat`, `setup-macos.command`, `start-windows.bat`, `start-macos.command`, `Python 3.13`, `SAM2`, and `Conda is not used`; and does not contain `uv sync --extra gpu`, `uv run --extra gpu`, or `Python 3.14+`.

Use explicit `assertIn`/`assertNotIn` calls rather than regexes.

- [ ] **Step 2: Run documentation contracts and verify RED**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_environment_contracts.py -q
```

Expected: README assertions fail against the old setup commands and Python requirement.

- [ ] **Step 3: Rewrite README environment sections**

Document this flow:

```markdown
## Requirements

- Windows 10/11 with an NVIDIA GPU and current driver, or macOS with MPS-capable hardware
- uv
- Node.js and npm

Python 3.13 is installed and managed by uv. Conda is not used.

## Full setup

Windows: `setup-windows.bat`

macOS: `./setup-macos.command`

Full setup installs the platform PyTorch build, pinned SAM2, the default checkpoint,
frontend dependencies, and verifies a real segmentation inference before succeeding.

## Launch

Windows: `start-windows.bat`

macOS: `./start-macos.command`

Launch is offline and never installs, syncs, builds, downloads, or kills processes.
Rerun the platform setup script after dependency or frontend changes.
```

Add recovery examples for missing uv/Node, stale `.venv`, occupied port 7438, CUDA/MPS unavailable, and incomplete SAM2 setup. Update `FEATURES.md` to describe SAM2 as required by full setup and remove runtime auto-install language.

- [ ] **Step 4: Run documentation contracts and verify GREEN**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_environment_contracts.py -q
```

Expected: all documentation and environment contracts pass.

- [ ] **Step 5: Commit documentation**

```powershell
git add README.md FEATURES.md tests/test_environment_contracts.py
git commit -m "docs: document clean platform setup and launch"
```

### Task 9: Verify Windows full setup without Conda leakage

**Files:**
- Inspect: `.venv`
- Inspect: `uv.lock`
- Inspect: SAM2 checkpoint under the configured workspace model directory

- [ ] **Step 1: Capture the active-shell contamination baseline**

Run:

```powershell
python --version
$env:CONDA_PREFIX
Get-Command python | Select-Object Source
```

Expected on the current machine: shell Python may resolve to Miniconda 3.11 and `CONDA_PREFIX` may be set. This is test input, not a supported project interpreter.

- [ ] **Step 2: Run the real Windows setup**

Run:

```powershell
cmd /c setup-windows.bat
```

Expected: exact sync succeeds, frontend builds, checkpoint exists, diagnostic reports Python 3.13, `torch==2.6.0+cu124`, matching Torchvision, RTX 3090 CUDA availability, importable pinned SAM2, and successful smoke inference. No reported path may contain Miniconda/Anaconda.

- [ ] **Step 3: Verify launch is offline and non-mutating**

Record hashes and package state:

```powershell
git hash-object uv.lock
uv pip freeze --python .venv\Scripts\python.exe
```

Run the quick diagnostic and start launcher with network disabled or unavailable, then stop with Ctrl+C:

```powershell
uv run --locked --no-sync python -m web.env_check --backend cuda
cmd /c start-windows.bat
```

Repeat the lock hash and package freeze. Expected: identical outputs; no dependency, asset, model, or lockfile change.

- [ ] **Step 4: Commit any diagnostic-only correction**

If the real setup exposes an implementation defect, return to the task that owns it, add a failing automated regression, make the minimal fix, and recommit there. Do not create a catch-all verification commit.

### Task 10: Run complete automated verification

**Files:**
- Inspect: all modified files
- Inspect: Git working tree

- [ ] **Step 1: Run lock, backend, frontend, and source checks**

Run:

```powershell
uv lock --check
uv run --isolated --locked python -m pytest -q
Set-Location frontend
npm run check
npm run build
Set-Location ..
git diff --check
```

Expected: lock current; all backend tests pass; Svelte has 0 errors (existing accessibility warnings remain separately tracked); Vite build succeeds; no authored-file whitespace errors.

- [ ] **Step 2: Run the full Playwright suite twice**

Run from `frontend` twice:

```powershell
npm run e2e
npm run e2e
```

Expected each time: all 84 tests pass with 0 failed, 0 flaky, and 0 skipped. The backend command must report the isolated uv environment and must not alter `.venv`.

- [ ] **Step 3: Verify repository and application environment stability**

Run:

```powershell
git status --short --branch
uv sync --locked --extra cuda --extra sam2 --dry-run
uv run --locked --no-sync python -m web.env_check --backend cuda --smoke
```

Expected: clean working tree, uv would make no changes, and the real Windows CUDA/SAM2 smoke passes.

- [ ] **Step 4: Record the macOS release gate**

Do not claim full macOS completion on Windows. Record the exact target-Mac commands in the final handoff:

```sh
./setup-macos.command
uv run --locked --no-sync python -m web.env_check --backend mps --smoke
./start-macos.command
```

Expected on the target Mac: setup and MPS/SAM2 smoke pass, then the server starts without syncing or building.

- [ ] **Step 5: Final commit if and only if tracked verification artifacts changed intentionally**

Normally no commit is needed. If documentation was corrected to record an observed, stable platform constraint, stage only that documentation and commit with a specific message.

### Task 11: Publish the environment cleanup branch

**Files:**
- Inspect: Git history and diff against `main`

- [ ] **Step 1: Review branch scope**

Run:

```powershell
git status --short --branch
git log --oneline main..HEAD
git diff --stat main...HEAD
```

Expected: clean branch containing only dependency, diagnostic, setup/launch, server, test-isolation, and documentation changes from this plan.

- [ ] **Step 2: Push the branch**

```powershell
git push -u origin codex/clean-cross-platform-environment
```

Expected: remote branch points at local HEAD. Do not merge until the target-Mac hardware gate is either completed or explicitly accepted as a post-merge release gate by the user.
