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
    parser = argparse.ArgumentParser(description="Validate the Plotter Studio environment")
    parser.add_argument("--backend", required=True, choices=("cuda", "mps"))
    parser.add_argument("--checkpoint")
    parser.add_argument("--download-checkpoint", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _module_file(name: str) -> Path | None:
    import importlib

    try:
        module = importlib.import_module(name)
    except Exception:
        return None
    path = getattr(module, "__file__", None)
    return Path(path) if path else None


def main(argv=None) -> int:
    args = parse_args(argv)
    details: dict[str, str] = {}
    errors: list[str] = []

    errors += python_errors(sys.version_info[:3])

    module_paths = [p for p in (_module_file("torch"), _module_file("torchvision"), _module_file("sam2")) if p]
    errors += conda_errors(
        executable=Path(sys.executable),
        base_prefix=Path(sys.base_prefix),
        module_paths=module_paths,
        environ=dict(os.environ),
    )

    try:
        import torch  # noqa: F401
    except Exception as exc:  # pragma: no cover - import failure path
        errors.append(f"PyTorch import failed: {exc}")
        torch = None

    if torch is not None:
        acc_details, acc_errors = accelerator_status(torch, args.backend)
        details.update(acc_details)
        errors += acc_errors

    if args.download_checkpoint or args.smoke:
        errors.append("Checkpoint download and smoke inference are not implemented")

    if args.json:
        print(json.dumps({"details": details, "errors": errors}))
    else:
        for key, value in details.items():
            print(f"{key}: {value}")
    for error in errors:
        print(error, file=sys.stderr)

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
