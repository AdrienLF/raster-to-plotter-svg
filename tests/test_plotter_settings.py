import json
import tempfile
import unittest
from pathlib import Path

import web.server as server


class PlotterSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_settings_path = server.SETTINGS_PATH
        server.SETTINGS_PATH = Path(self.tmp.name) / "settings.json"

    def tearDown(self):
        server.SETTINGS_PATH = self.old_settings_path
        self.tmp.cleanup()

    def test_load_cfg_migrates_legacy_usb_port_to_network_bridge(self):
        server.SETTINGS_PATH.write_text(json.dumps({"port": "/dev/ttyACM0"}))

        cfg = server.load_cfg()

        self.assertEqual(cfg["port"], "socket://100.92.241.24:4000")

    def test_load_cfg_preserves_custom_port(self):
        server.SETTINGS_PATH.write_text(json.dumps({"port": "/Users/adrien/.idraw-tty"}))

        cfg = server.load_cfg()

        self.assertEqual(cfg["port"], "/Users/adrien/.idraw-tty")


if __name__ == "__main__":
    unittest.main()
