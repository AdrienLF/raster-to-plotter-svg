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


def run_predictor_smoke(predictor, np, torch):
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    point_coords = np.array([[16, 16]])
    point_labels = np.array([1])
    predictor.set_image(image)
    # ponytail: real torch.inference_mode() is a context manager; a test Mock is not,
    # so fall back to a no-op context when the protocol is absent.
    import contextlib

    cm = torch.inference_mode()
    if not hasattr(type(cm), "__enter__"):
        cm = contextlib.nullcontext()
    with cm:
        masks, _scores, _low = predictor.predict(
            point_coords=point_coords,
            point_labels=point_labels,
            multimask_output=False,
        )
    if masks is None or getattr(masks, "size", 0) == 0:
        raise RuntimeError("SAM2 smoke inference returned no masks")
    return masks


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

    if args.smoke and torch is not None and not errors:
        try:
            import numpy as np

            checkpoint = Path(
                args.checkpoint
                or os.environ.get("SAM2_CHECKPOINT")
                or Path.home() / ".plotter_studio" / "models" / f"{DEFAULT_MODEL}.pt"
            )
            checkpoint = prepare_checkpoint(
                checkpoint,
                DEFAULT_CHECKPOINT_URL,
                allow_download=args.download_checkpoint,
            )
            from sam2.build_sam import build_sam2
            from sam2.sam2_image_predictor import SAM2ImagePredictor

            model = build_sam2(DEFAULT_CONFIG, str(checkpoint), device=args.backend)
            predictor = SAM2ImagePredictor(model)
            run_predictor_smoke(predictor, np, torch)
            details["sam2_smoke"] = "ok"
        except Exception as exc:
            errors.append(f"SAM2 smoke inference failed: {exc}")
    elif args.download_checkpoint and not args.smoke:
        try:
            checkpoint = Path(
                args.checkpoint
                or os.environ.get("SAM2_CHECKPOINT")
                or Path.home() / ".plotter_studio" / "models" / f"{DEFAULT_MODEL}.pt"
            )
            prepare_checkpoint(checkpoint, DEFAULT_CHECKPOINT_URL, allow_download=True)
            details["sam2_checkpoint"] = "ready"
        except Exception as exc:
            errors.append(f"SAM2 checkpoint preparation failed: {exc}")

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
