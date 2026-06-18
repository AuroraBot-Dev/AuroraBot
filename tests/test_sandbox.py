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


# ═══════════════════════════════════════════════════════════════
# AccessPolicySnapshot
# ═══════════════════════════════════════════════════════════════


class AccessPolicySnapshotTest(unittest.TestCase):
    def test_snapshot_is_immutable(self) -> None:
        """快照应该是不可变的数据结构。"""
        config = SandboxConfig(
            whitelist_files=frozenset({"data/**"}),
            whitelist_dirs=frozenset({"data/**"}),
            whitelist_modules=frozenset({"json"}),
            whitelist_builtins=frozenset({"len"}),
            blacklist_files=frozenset(),
            blacklist_dirs=frozenset(),
            blacklist_modules=frozenset({"os"}),
            blacklist_builtins=frozenset({"exec"}),
        )
        policy = AccessPolicy(config)
        snapshot = policy.snapshot()
        from src.brain.sandbox.policy import AccessPolicySnapshot

        self.assertIsInstance(snapshot, AccessPolicySnapshot)
        self.assertIsInstance(snapshot.whitelist_modules, frozenset)
        self.assertIn("json", snapshot.whitelist_modules)
        self.assertIn("os", snapshot.blacklist_modules)

    def test_snapshot_independent_of_later_config_change(self) -> None:
        """快照应该独立于后续的配置变更。"""
        config = SandboxConfig(
            whitelist_files=frozenset({"data/**"}),
            whitelist_dirs=frozenset({"data/**"}),
            whitelist_modules=frozenset({"json"}),
            whitelist_builtins=frozenset({"len"}),
            blacklist_files=frozenset(),
            blacklist_dirs=frozenset(),
            blacklist_modules=frozenset({"os"}),
            blacklist_builtins=frozenset({"exec"}),
        )
        policy = AccessPolicy(config)
        snapshot = policy.snapshot()
        # 更新配置
        new_config = SandboxConfig(
            whitelist_files=frozenset({"data/**"}),
            whitelist_dirs=frozenset({"data/**"}),
            whitelist_modules=frozenset({"json", "math"}),
            whitelist_builtins=frozenset({"len", "print"}),
            blacklist_files=frozenset(),
            blacklist_dirs=frozenset(),
            blacklist_modules=frozenset({"os"}),
            blacklist_builtins=frozenset({"exec"}),
        )
        policy.update_config(new_config)
        # 快照不受影响
        self.assertNotIn("math", snapshot.whitelist_modules)
        self.assertNotIn("print", snapshot.whitelist_builtins)
