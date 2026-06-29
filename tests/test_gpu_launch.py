import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LaunchContractTest(unittest.TestCase):
    def test_launchers_never_install_build_download_or_kill(self):
        for relative in ("start-studio.bat", "start-studio.command", "web/run.sh"):
            source = (ROOT / relative).read_text(encoding="utf-8").lower()
            with self.subTest(relative=relative):
                for forbidden in (
                    "uv sync", "npm install", "npm ci", "npm run build",
                    "taskkill", "kill -9", "--download-checkpoint",
                ):
                    self.assertNotIn(forbidden, source)

    def test_platform_launchers_clear_conda_and_do_not_sync(self):
        windows = (ROOT / "start-studio.bat").read_text(encoding="utf-8")
        macos = (ROOT / "start-studio.command").read_text(encoding="utf-8")
        self.assertIn('set "CONDA_PREFIX="', windows)
        self.assertIn("unset CONDA_PREFIX", macos)
        self.assertIn("uv run --locked --no-sync", windows)
        self.assertIn("uv run --locked --no-sync", macos)

    def test_launchers_run_quick_environment_check(self):
        self.assertIn(
            "-m web.env_check --backend cuda",
            (ROOT / "start-studio.bat").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "-m web.env_check --backend mps",
            (ROOT / "start-studio.command").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
