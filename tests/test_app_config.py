import tempfile
import unittest
from pathlib import Path

from src.platform.app_config import load_apps_config
from src.platform.app_discovery import discover_apps, instantiate_app


class AppConfigTest(unittest.TestCase):
    def test_missing_config_creates_template_and_skips_loading(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            loaded = load_apps_config(config_path)
            self.assertEqual(loaded, {})
            self.assertTrue(config_path.exists())

            loaded = load_apps_config(config_path)
            self.assertIn("qq", loaded)
            self.assertIn("diary", loaded)
            self.assertIn("clock", loaded)
            self.assertTrue(loaded["qq"]["enabled"])
            self.assertEqual(loaded["qq"]["startup"]["enable_listener"], True)

    def test_discovery_and_instantiation_are_dynamic(self) -> None:
        discovered = discover_apps()
        self.assertIn("qq", discovered)
        self.assertIn("diary", discovered)
        self.assertIn("clock", discovered)

        app = instantiate_app("qq", {"enable_listener": False, "unknown": 1})
        self.assertEqual(app.__class__.__name__, "QQApplication")
        self.assertFalse(app._enable_listener)


if __name__ == "__main__":
    unittest.main()
