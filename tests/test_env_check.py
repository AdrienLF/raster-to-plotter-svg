import tempfile
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

    def test_prepare_checkpoint_downloads_only_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sam2.1_hiera_tiny.pt"
            download = mock.Mock(side_effect=lambda url, dest: dest.write_bytes(b"x"))

            result = env_check.prepare_checkpoint(
                target,
                "https://example.test/model.pt",
                allow_download=True,
                downloader=download,
            )

            self.assertEqual(result, target)
            download.assert_called_once_with("https://example.test/model.pt", target)

    def test_missing_checkpoint_without_download_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "checkpoint is missing"):
                env_check.prepare_checkpoint(
                    Path(tmp) / "missing.pt",
                    "https://example.test/model.pt",
                    allow_download=False,
                    downloader=mock.Mock(),
                )

    def test_smoke_inference_requires_a_nonempty_mask(self):
        predictor = mock.Mock()
        predictor.predict.return_value = (mock.Mock(size=0), [], None)

        with self.assertRaisesRegex(RuntimeError, "no masks"):
            env_check.run_predictor_smoke(predictor, mock.Mock(), mock.Mock())


if __name__ == "__main__":
    unittest.main()
