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
