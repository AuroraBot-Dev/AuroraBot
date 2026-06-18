"""sandbox 沙箱组件测试。"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from src.brain.sandbox.base import SandboxConfigError
from src.brain.sandbox.settings import SandboxConfig

# ═══════════════════════════════════════════════════════════════
# SandboxConfig
# ═══════════════════════════════════════════════════════════════


class SandboxConfigTest(unittest.TestCase):
    def test_from_yaml_valid(self) -> None:
        yaml_content = textwrap.dedent("""\
            whitelist:
              files: ["data/**"]
              dirs: ["data/**"]
              modules: ["json", "math"]
              builtins: ["len", "print"]
            blacklist:
              files: []
              dirs: []
              modules: ["os", "sys"]
              builtins: ["exec", "eval"]
        """)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(yaml_content)
            f.flush()
            config = SandboxConfig.from_yaml(Path(f.name))

        self.assertIn("json", config.whitelist_modules)
        self.assertIn("math", config.whitelist_modules)
        self.assertIn("os", config.blacklist_modules)
        self.assertIn("exec", config.blacklist_builtins)
        self.assertIsInstance(config.whitelist_files, frozenset)
        self.assertIsInstance(config.blacklist_modules, frozenset)

    def test_from_yaml_missing_key_raises(self) -> None:
        yaml_content = textwrap.dedent("""\
            whitelist:
              files: []
              dirs: []
              modules: []
              builtins: []
        """)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(yaml_content)
            f.flush()
            with self.assertRaises(SandboxConfigError):
                SandboxConfig.from_yaml(Path(f.name))

    def test_from_yaml_wrong_type_raises(self) -> None:
        yaml_content = textwrap.dedent("""\
            whitelist:
              files: "not a list"
              dirs: []
              modules: []
              builtins: []
            blacklist:
              files: []
              dirs: []
              modules: []
              builtins: []
        """)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(yaml_content)
            f.flush()
            with self.assertRaises(SandboxConfigError):
                SandboxConfig.from_yaml(Path(f.name))

    def test_from_yaml_file_not_found(self) -> None:
        with self.assertRaises(SandboxConfigError):
            SandboxConfig.from_yaml(Path("/nonexistent/path.yaml"))
