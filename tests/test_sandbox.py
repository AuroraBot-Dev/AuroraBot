"""sandbox 沙箱组件测试。"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from src.brain.sandbox.base import SandboxConfigError
from src.brain.sandbox.policy import AccessPolicy
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


# ═══════════════════════════════════════════════════════════════
# AccessPolicy
# ═══════════════════════════════════════════════════════════════


class AccessPolicyTest(unittest.TestCase):
    def test_default_deny_all(self) -> None:
        """空配置时所有访问都应该被拒绝。"""
        empty_config = SandboxConfig(
            whitelist_files=frozenset(),
            whitelist_dirs=frozenset(),
            whitelist_modules=frozenset(),
            whitelist_builtins=frozenset(),
            blacklist_files=frozenset(),
            blacklist_dirs=frozenset(),
            blacklist_modules=frozenset(),
            blacklist_builtins=frozenset(),
        )
        policy = AccessPolicy(empty_config)
        self.assertFalse(policy.can_import_module("json"))
        self.assertFalse(policy.can_use_builtin("len"))

    def test_blacklist_overrides_whitelist(self) -> None:
        """黑名单优先级高于白名单。"""
        config = SandboxConfig(
            whitelist_files=frozenset(),
            whitelist_dirs=frozenset(),
            whitelist_modules=frozenset({"os"}),
            whitelist_builtins=frozenset({"exec"}),
            blacklist_files=frozenset(),
            blacklist_dirs=frozenset(),
            blacklist_modules=frozenset({"os"}),
            blacklist_builtins=frozenset({"exec"}),
        )
        policy = AccessPolicy(config)
        self.assertFalse(policy.can_import_module("os"))
        self.assertFalse(policy.can_use_builtin("exec"))

    def test_module_prefix_match(self) -> None:
        """禁止 os 时 os.path 也应该被禁止。"""
        config = SandboxConfig(
            whitelist_files=frozenset(),
            whitelist_dirs=frozenset(),
            whitelist_modules=frozenset(),
            whitelist_builtins=frozenset(),
            blacklist_files=frozenset(),
            blacklist_dirs=frozenset(),
            blacklist_modules=frozenset({"os"}),
            blacklist_builtins=frozenset(),
        )
        policy = AccessPolicy(config)
        self.assertFalse(policy.can_import_module("os"))
        self.assertFalse(policy.can_import_module("os.path"))
        self.assertFalse(policy.can_import_module("os.path.join"))

    def test_whitelist_module_allowed(self) -> None:
        """在白名单中的模块应该被允许。"""
        config = SandboxConfig(
            whitelist_files=frozenset(),
            whitelist_dirs=frozenset(),
            whitelist_modules=frozenset({"json", "math"}),
            whitelist_builtins=frozenset(),
            blacklist_files=frozenset(),
            blacklist_dirs=frozenset(),
            blacklist_modules=frozenset(),
            blacklist_builtins=frozenset(),
        )
        policy = AccessPolicy(config)
        self.assertTrue(policy.can_import_module("json"))
        self.assertTrue(policy.can_import_module("math"))

    def test_blacklist_module_denied(self) -> None:
        """在黑名单中的模块应该被拒绝。"""
        config = SandboxConfig(
            whitelist_files=frozenset(),
            whitelist_dirs=frozenset(),
            whitelist_modules=frozenset(),
            whitelist_builtins=frozenset(),
            blacklist_files=frozenset(),
            blacklist_dirs=frozenset(),
            blacklist_modules=frozenset({"subprocess", "sys"}),
            blacklist_builtins=frozenset(),
        )
        policy = AccessPolicy(config)
        self.assertFalse(policy.can_import_module("subprocess"))
        self.assertFalse(policy.can_import_module("sys"))

    def test_builtin_whitelist_allowed(self) -> None:
        """在白名单中的内置函数应该被允许。"""
        config = SandboxConfig(
            whitelist_files=frozenset(),
            whitelist_dirs=frozenset(),
            whitelist_modules=frozenset(),
            whitelist_builtins=frozenset({"len", "print"}),
            blacklist_files=frozenset(),
            blacklist_dirs=frozenset(),
            blacklist_modules=frozenset(),
            blacklist_builtins=frozenset(),
        )
        policy = AccessPolicy(config)
        self.assertTrue(policy.can_use_builtin("len"))
        self.assertTrue(policy.can_use_builtin("print"))

    def test_builtin_blacklist_denied(self) -> None:
        """在黑名单中的内置函数应该被拒绝。"""
        config = SandboxConfig(
            whitelist_files=frozenset(),
            whitelist_dirs=frozenset(),
            whitelist_modules=frozenset(),
            whitelist_builtins=frozenset(),
            blacklist_files=frozenset(),
            blacklist_dirs=frozenset(),
            blacklist_modules=frozenset(),
            blacklist_builtins=frozenset({"exec", "eval", "open"}),
        )
        policy = AccessPolicy(config)
        self.assertFalse(policy.can_use_builtin("exec"))
        self.assertFalse(policy.can_use_builtin("eval"))
        self.assertFalse(policy.can_use_builtin("open"))
