"""sandbox 沙箱组件测试。"""

from __future__ import annotations

import asyncio
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.brain.sandbox.base import SandboxConfigError, SecurityViolation
from src.brain.sandbox.policy import AccessPolicy
from src.brain.sandbox.settings import SandboxConfig

# ═══════════════════════════════════════════════════════════════
# SandboxConfig
# ═══════════════════════════════════════════════════════════════


class SandboxConfigTest(unittest.TestCase):
    def test_from_yaml_valid(self) -> None:
        yaml_content = textwrap.dedent("""\
            whitelist:
              files: ["PROJECT_DIR/data/**"]
              dirs: ["PROJECT_DIR/data/**"]
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


# ═══════════════════════════════════════════════════════════════
# CodeInspector
# ═══════════════════════════════════════════════════════════════


class CodeInspectorDangerousNodeTest(unittest.TestCase):
    def setUp(self) -> None:
        config = SandboxConfig(
            whitelist_files=frozenset({"data/sandbox/**"}),
            whitelist_dirs=frozenset({"data/sandbox/**"}),
            whitelist_modules=frozenset({"json", "math", "re"}),
            whitelist_builtins=frozenset({"len", "print", "range", "int", "str"}),
            blacklist_files=frozenset(),
            blacklist_dirs=frozenset(),
            blacklist_modules=frozenset({"os", "sys", "subprocess"}),
            blacklist_builtins=frozenset({"exec", "eval", "compile", "__import__", "globals", "locals"}),
        )
        self.policy = AccessPolicy(config)
        from src.brain.sandbox.inspector import CodeInspector

        self.inspector = CodeInspector(self.policy)

    def test_safe_code_passes(self) -> None:
        """安全代码应该通过检查。"""
        code = "x = 1 + 2\nprint(x)\n"
        violations = self.inspector.inspect(code)
        self.assertEqual(violations, [])

    def test_delete_statement_rejected(self) -> None:
        """del 语句应该被拒绝。"""
        code = "x = 1\ndel x\n"
        violations = self.inspector.inspect(code)
        self.assertTrue(any(v.violation_type == "dangerous_operation" for v in violations))
        self.assertTrue(any("Delete" in (v.node_name or "") for v in violations))

    def test_global_statement_rejected(self) -> None:
        """global 语句应该被拒绝。"""
        code = "def f():\n    global x\n"
        violations = self.inspector.inspect(code)
        self.assertTrue(any(v.node_name == "Global" for v in violations))

    def test_exec_call_rejected(self) -> None:
        """exec() 调用应该被拒绝。"""
        code = 'exec("print(1)")\n'
        violations = self.inspector.inspect(code)
        self.assertTrue(any("exec" in v.detail for v in violations))

    def test_eval_call_rejected(self) -> None:
        """eval() 调用应该被拒绝。"""
        code = 'eval("1+1")\n'
        violations = self.inspector.inspect(code)
        self.assertTrue(any("eval" in v.detail for v in violations))

    def test_os_import_rejected(self) -> None:
        """import os 应该被拒绝。"""
        code = "import os\n"
        violations = self.inspector.inspect(code)
        self.assertTrue(any(v.violation_type == "blacklisted_access" for v in violations))

    def test_subprocess_import_rejected(self) -> None:
        """import subprocess 应该被拒绝。"""
        code = "import subprocess\n"
        violations = self.inspector.inspect(code)
        self.assertTrue(any("subprocess" in v.detail for v in violations))

    def test_import_from_rejected(self) -> None:
        """from os import system 应该被拒绝。"""
        code = "from os import system\n"
        violations = self.inspector.inspect(code)
        self.assertTrue(any("os" in v.detail for v in violations))

    def test_safe_import_allowed(self) -> None:
        """import json 应该被允许。"""
        code = "import json\n"
        violations = self.inspector.inspect(code)
        self.assertEqual(violations, [])

    def test_import_with_alias_rejected(self) -> None:
        """import os as x 应该被拒绝（别名不影响模块检查）。"""
        code = "import os as operating_system\n"
        violations = self.inspector.inspect(code)
        self.assertTrue(any("os" in v.detail for v in violations))

    def test_from_import_with_alias_rejected(self) -> None:
        """from os import path as p 应该被拒绝。"""
        code = "from os import path as p\n"
        violations = self.inspector.inspect(code)
        self.assertTrue(any("os" in v.detail for v in violations))


# ═══════════════════════════════════════════════════════════════
# CodeInspector Advanced Tests
# ═══════════════════════════════════════════════════════════════


class CodeInspectorAdvancedTest(unittest.TestCase):
    def setUp(self) -> None:
        config = SandboxConfig(
            whitelist_files=frozenset({"data/sandbox/**"}),
            whitelist_dirs=frozenset({"data/sandbox/**"}),
            whitelist_modules=frozenset({"json", "math", "re", "pathlib"}),
            whitelist_builtins=frozenset({"len", "print", "range", "int", "str", "getattr"}),
            blacklist_files=frozenset(),
            blacklist_dirs=frozenset(),
            blacklist_modules=frozenset(
                {
                    "os",
                    "sys",
                    "subprocess",
                    "operator",
                    "gc",
                    "inspect",
                    "linecache",
                    "traceback",
                }
            ),
            blacklist_builtins=frozenset({"exec", "eval", "compile", "__import__", "globals", "locals", "open"}),
        )
        self.policy = AccessPolicy(config)
        from src.brain.sandbox.inspector import CodeInspector

        self.inspector = CodeInspector(self.policy)

    def test_str_format_rejected(self) -> None:
        code = '"{0.__class__}".format(x)\n'
        violations = self.inspector.inspect(code)
        self.assertTrue(any("str.format" in v.detail for v in violations))

    def test_subclasses_access_rejected(self) -> None:
        code = "x.__subclasses__()\n"
        violations = self.inspector.inspect(code)
        self.assertTrue(any("__subclasses__" in v.detail for v in violations))

    def test_chained_class_access_rejected(self) -> None:
        code = "[].__class__.__base__.__subclasses__()\n"
        violations = self.inspector.inspect(code)
        self.assertTrue(any("__class__" in v.detail for v in violations))

    def test_type_introspection_bases_rejected(self) -> None:
        code = "type(x).__bases__\n"
        violations = self.inspector.inspect(code)
        self.assertTrue(any("type()" in v.detail for v in violations))

    def test_type_introspection_subclasses_rejected(self) -> None:
        code = "type(x).__subclasses__()\n"
        violations = self.inspector.inspect(code)
        self.assertTrue(any("type()" in v.detail for v in violations))

    def test_type_introspection_globals_rejected(self) -> None:
        code = "type(lambda:0).__globals__\n"
        violations = self.inspector.inspect(code)
        self.assertTrue(any("type()" in v.detail for v in violations))

    def test_type_call_allowed(self) -> None:
        code = "t = type(x)\n"
        violations = self.inspector.inspect(code)
        type_violations = [v for v in violations if "type()" in v.detail]
        self.assertEqual(type_violations, [])

    def test_symlink_to_rejected(self) -> None:
        code = 'from pathlib import Path\nPath("x").symlink_to("y")\n'
        violations = self.inspector.inspect(code)
        self.assertTrue(any("symlink_to" in v.detail for v in violations))

    def test_hardlink_to_rejected(self) -> None:
        code = 'from pathlib import Path\nPath("x").hardlink_to("y")\n'
        violations = self.inspector.inspect(code)
        self.assertTrue(any("hardlink_to" in v.detail for v in violations))

    def test_getattribute_rejected(self) -> None:
        code = 'x.__getattribute__("__class__")\n'
        violations = self.inspector.inspect(code)
        self.assertTrue(any("__getattribute__" in v.detail for v in violations))

    def test_attrgetter_rejected(self) -> None:
        code = 'from operator import attrgetter\nattrgetter("__class__")([])\n'
        violations = self.inspector.inspect(code)
        self.assertTrue(any("attrgetter" in v.detail for v in violations))

    def test_open_blacklisted_path_rejected(self) -> None:
        code = 'open("/etc/passwd")\n'
        violations = self.inspector.inspect(code)
        self.assertTrue(any("open" in v.detail for v in violations))

    def test_open_write_outside_rejected(self) -> None:
        code = 'open("/tmp/x", "w")\n'
        violations = self.inspector.inspect(code)
        self.assertTrue(any("open" in v.detail for v in violations))

    def test_syntax_error_returns_no_violations(self) -> None:
        code = "def f(\n"
        violations = self.inspector.inspect(code)
        self.assertEqual(violations, [])


# ═══════════════════════════════════════════════════════════════
# SandboxExecutor
# ═══════════════════════════════════════════════════════════════


class SandboxExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        config = SandboxConfig(
            whitelist_files=frozenset({"data/sandbox/**"}),
            whitelist_dirs=frozenset({"data/sandbox/**"}),
            whitelist_modules=frozenset({"json", "math", "re"}),
            whitelist_builtins=frozenset(
                {
                    "len",
                    "print",
                    "range",
                    "int",
                    "str",
                    "list",
                    "dict",
                    "set",
                    "tuple",
                    "float",
                    "bool",
                    "type",
                    "isinstance",
                    "repr",
                    "format",
                    "sorted",
                    "min",
                    "max",
                    "sum",
                    "abs",
                    "round",
                    "enumerate",
                    "zip",
                    "map",
                    "filter",
                    "any",
                    "all",
                    "iter",
                    "next",
                    "input",
                }
            ),
            blacklist_files=frozenset(),
            blacklist_dirs=frozenset(),
            blacklist_modules=frozenset(
                {"os", "sys", "subprocess", "shutil", "builtins", "importlib", "ctypes", "gc", "inspect"}
            ),
            blacklist_builtins=frozenset(
                {
                    "exec",
                    "eval",
                    "compile",
                    "__import__",
                    "globals",
                    "locals",
                    "breakpoint",
                    "exit",
                    "quit",
                    "getattr",
                    "setattr",
                    "open",
                    "vars",
                    "dir",
                    "hash",
                    "id",
                    "callable",
                    "hasattr",
                    "chr",
                    "ord",
                    "hex",
                    "oct",
                    "bin",
                    "divmod",
                    "pow",
                }
            ),
        )
        self.policy = AccessPolicy(config)
        from src.brain.sandbox.inspector import CodeInspector

        self.inspector = CodeInspector(self.policy)
        from src.brain.sandbox.executor import SandboxExecutor

        self.executor = SandboxExecutor(self.policy, self.inspector)

    def test_simple_print_captured(self) -> None:
        async def run() -> None:
            result = await self.executor.execute('print("hello")', "test-session")
            self.assertTrue(result.success)
            self.assertIn("hello", result.output)
            self.assertIsNone(result.error)

        asyncio.run(run())

    def test_syntax_error_returns_error(self) -> None:
        async def run() -> None:
            result = await self.executor.execute("def f(\n", "test-session")
            self.assertFalse(result.success)
            self.assertIn("SyntaxError", result.error)

        asyncio.run(run())

    def test_no_stdout_direct_output(self) -> None:
        """stdout 应被捕获到文件，不会直接输出到控制台。"""

        async def run() -> None:
            result = await self.executor.execute('print("should not appear in console")', "test-session")
            self.assertTrue(result.success)
            self.assertIn("should not appear in console", result.output)

        asyncio.run(run())


# ═══════════════════════════════════════════════════════════════
# ConfigReloader
# ═══════════════════════════════════════════════════════════════


class ConfigReloaderTest(unittest.TestCase):
    def test_reload_on_mtime_change(self) -> None:
        yaml_content = textwrap.dedent("""\
            whitelist:
              files: []
              dirs: []
              modules: ["json"]
              builtins: ["len"]
            blacklist:
              files: []
              dirs: []
              modules: ["os"]
              builtins: ["exec"]
        """)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        configs_received: list[SandboxConfig] = []

        def on_update(cfg: SandboxConfig) -> None:
            configs_received.append(cfg)

        from src.brain.sandbox.settings import ConfigReloader

        reloader = ConfigReloader(path, callback=on_update)
        reloader.check_and_reload()
        self.assertEqual(len(configs_received), 1)
        self.assertIn("json", configs_received[0].whitelist_modules)

        # 修改文件
        import time

        time.sleep(0.1)  # 确保 mtime 变化
        yaml_content2 = textwrap.dedent("""\
            whitelist:
              files: []
              dirs: []
              modules: ["json", "math"]
              builtins: ["len", "print"]
            blacklist:
              files: []
              dirs: []
              modules: ["os"]
              builtins: ["exec"]
        """)
        path.write_text(yaml_content2, encoding="utf-8")
        reloader.check_and_reload()
        self.assertEqual(len(configs_received), 2)
        self.assertIn("math", configs_received[1].whitelist_modules)

    def test_invalid_yaml_keeps_previous_config(self) -> None:
        yaml_content = textwrap.dedent("""\
            whitelist:
              files: []
              dirs: []
              modules: ["json"]
              builtins: ["len"]
            blacklist:
              files: []
              dirs: []
              modules: ["os"]
              builtins: ["exec"]
        """)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        configs_received: list[SandboxConfig] = []
        from src.brain.sandbox.settings import ConfigReloader

        def on_config(cfg: SandboxConfig) -> None:
            configs_received.append(cfg)

        reloader = ConfigReloader(path, callback=on_config)
        reloader.check_and_reload()
        self.assertEqual(len(configs_received), 1)

        # 写入无效 YAML
        import time

        time.sleep(0.1)
        path.write_text("not: valid: yaml: [", encoding="utf-8")
        reloader.check_and_reload()
        # callback 不应被调用（无效配置不触发更新）
        self.assertEqual(len(configs_received), 1)


# ═══════════════════════════════════════════════════════════════
# SandboxManager
# ═══════════════════════════════════════════════════════════════

from src.brain.sandbox import SandboxManager, SandboxResult


class SandboxManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = SandboxManager()

    def test_full_safe_execution(self) -> None:
        async def run() -> None:
            result = await self.manager.execute('print("hello world")', "test-safe")
            self.assertIsInstance(result, SandboxResult)
            self.assertTrue(result.success)
            self.assertIn("hello world", result.output)

        asyncio.run(run())

    def test_full_dangerous_rejection(self) -> None:
        async def run() -> None:
            result = await self.manager.execute('import os\nos.system("rm -rf /")', "test-danger")
            self.assertFalse(result.success)
            self.assertIn("安全违规", result.error)

        asyncio.run(run())

    def test_syntax_error_in_manager(self) -> None:
        async def run() -> None:
            result = await self.manager.execute("def f(\n", "test-syntax")
            self.assertFalse(result.success)
            self.assertIn("语法错误", result.error)

        asyncio.run(run())

    def test_invalid_session_id(self) -> None:
        async def run() -> None:
            result = await self.manager.execute('print("x")', "../../../tmp")
            self.assertFalse(result.success)
            self.assertIn("非法字符", result.error)

        asyncio.run(run())

    def test_validate_session_id_valid(self) -> None:
        # 不应抛出异常
        SandboxManager._validate_session_id("test-session_123")

    def test_validate_session_id_invalid(self) -> None:
        with self.assertRaises(ValueError):
            SandboxManager._validate_session_id("../../../etc")


# ═══════════════════════════════════════════════════════════════
# SandboxManager 懒代理
# ═══════════════════════════════════════════════════════════════


class SandboxManagerProxyTest(unittest.TestCase):
    def test_proxy_delegates_to_manager(self) -> None:
        """proxy 的属性访问应代理到真实 SandboxManager。"""
        from src.brain.sandbox import _SandboxManagerProxy

        proxy = _SandboxManagerProxy()
        self.assertIsInstance(proxy, _SandboxManagerProxy)

    def test_get_sandbox_manager_returns_same_instance(self) -> None:
        """get_sandbox_manager 多次调用应返回同一单例。"""
        from src.brain.sandbox import get_sandbox_manager

        a = get_sandbox_manager()
        b = get_sandbox_manager()
        self.assertIs(a, b)


# ═══════════════════════════════════════════════════════════════
# SandboxManager 执行回调与格式化
# ═══════════════════════════════════════════════════════════════


class SandboxManagerCallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = SandboxManager()

    def test_on_result_callback_called(self) -> None:
        """on_result 回调应在执行完成后被调用。"""
        received: list[SandboxResult] = []

        def on_result(r: SandboxResult) -> None:
            received.append(r)

        async def run() -> None:
            await self.manager.execute('print("cb")', "test-cb", on_result=on_result)

        asyncio.run(run())
        self.assertEqual(len(received), 1)
        self.assertTrue(received[0].success)
        self.assertIn("cb", received[0].output)

    def test_format_violations_single(self) -> None:
        v = SecurityViolation(
            violation_type="dangerous_operation",
            detail="禁止调用 exec()",
            line=3,
            node_name="Call",
        )
        result = SandboxManager._format_violations([v])
        self.assertIn("dangerous_operation", result)
        self.assertIn("line 3", result)
        self.assertIn("[Call]", result)
        self.assertIn("禁止调用 exec()", result)

    def test_format_violations_multiple(self) -> None:
        v1 = SecurityViolation(violation_type="a", detail="d1", line=None, node_name=None)
        v2 = SecurityViolation(violation_type="b", detail="d2", line=1, node_name="Import")
        result = SandboxManager._format_violations([v1, v2])
        self.assertIn("d1", result)
        self.assertIn("d2", result)
        # v1 无 line 和 node_name
        self.assertNotIn("line None", result)

    def test_context_injection(self) -> None:
        """context 参数应注入到执行命名空间中。"""
        async def run() -> None:
            result = await self.manager.execute(
                'print(f"user={user}, score={score}")',
                "test-ctx",
                context={"user": "Alice", "score": 95.5},
            )
            self.assertTrue(result.success, f"Error: {result.error}")
            self.assertIn("user=Alice", result.output)
            self.assertIn("score=95.5", result.output)

        asyncio.run(run())

    def test_execution_time_populated(self) -> None:
        async def run() -> None:
            result = await self.manager.execute('print(1)', "test-time")
            self.assertGreater(result.execution_time, 0)

        asyncio.run(run())


# ═══════════════════════════════════════════════════════════════
# SandboxManager 安全拦截全链路
# ═══════════════════════════════════════════════════════════════


class SandboxManagerSecurityChainTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = SandboxManager()
        config = SandboxConfig(
            whitelist_files=frozenset({"data/sandbox/**"}),
            whitelist_dirs=frozenset({"data/sandbox/**"}),
            whitelist_modules=frozenset({"json", "math", "re"}),
            whitelist_builtins=frozenset({"len", "print", "range", "int", "str"}),
            blacklist_files=frozenset(),
            blacklist_dirs=frozenset(),
            blacklist_modules=frozenset({"os", "sys", "subprocess"}),
            blacklist_builtins=frozenset({"exec", "eval", "compile", "__import__", "globals", "locals"}),
        )
        self.policy = AccessPolicy(config)
        from src.brain.sandbox.inspector import CodeInspector
        self.inspector = CodeInspector(self.policy)

    async def _exec(self, code: str, sid: str = "test-sec") -> SandboxResult:
        return await self.manager.execute(code, sid)

    # ── 运行时拦截（通过 manager.execute 走完整链路）──

    def test_exec_banned(self) -> None:
        asyncio.run(self._assert_blocked('exec("print(1)")'))

    def test_eval_banned(self) -> None:
        asyncio.run(self._assert_blocked('eval("1+1")'))

    def test_del_statement_blocked(self) -> None:
        asyncio.run(self._assert_blocked('x = 1\ndel x'))

    def test_global_statement_blocked(self) -> None:
        asyncio.run(self._assert_blocked('def f():\n    global x'))

    def test_nonlocal_statement_blocked(self) -> None:
        asyncio.run(self._assert_blocked('def f():\n    x = 0\n    def g():\n        nonlocal x'))

    def test_subclasses_escape_blocked(self) -> None:
        asyncio.run(self._assert_blocked('[].__class__.__base__.__subclasses__()'))

    def test_breakpoint_blocked(self) -> None:
        asyncio.run(self._assert_blocked('breakpoint()'))

    def test_exit_blocked(self) -> None:
        asyncio.run(self._assert_blocked('exit()'))

    def test_safe_code_execution_passes(self) -> None:
        """纯计算代码（无需 import）应成功执行。"""
        asyncio.run(self._assert_allowed('x = [i**2 for i in range(10)]\nprint(x)'))

    def test_safe_print_execution_passes(self) -> None:
        asyncio.run(self._assert_allowed('print("hello sandbox")'))

    # ── AST 安全检查（通过 inspector 直接测试，不走执行）──

    def test_ast_os_import_blocked(self) -> None:
        violations = self.inspector.inspect('import os\nprint("hi")')
        self.assertTrue(any(v.violation_type == "blacklisted_access" for v in violations))

    def test_ast_from_os_import_blocked(self) -> None:
        violations = self.inspector.inspect('from os import system')
        self.assertTrue(any("os" in v.detail for v in violations))

    def test_ast_json_import_allowed(self) -> None:
        """import json 通过 AST 检查（在白名单内）。"""
        violations = self.inspector.inspect('import json\nprint(json.dumps({"a": 1}))')
        self.assertEqual(violations, [])

    def test_ast_math_import_allowed(self) -> None:
        violations = self.inspector.inspect('import math\nprint(math.pi)')
        self.assertEqual(violations, [])

    async def _assert_blocked(self, code: str) -> None:
        result = await self._exec(code)
        self.assertFalse(result.success, f"Expected blocked but succeeded: {result.output}")
        self.assertTrue(result.error)
        self.assertTrue(
            "安全违规" in result.error or "语法错误" in result.error,
            f"Unexpected error: {result.error}",
        )

    async def _assert_allowed(self, code: str) -> None:
        result = await self._exec(code)
        self.assertTrue(result.success, f"Expected allowed but blocked: {result.error}")


# ═══════════════════════════════════════════════════════════════
# SandboxExecutor 产物收集与磁盘检查
# ═══════════════════════════════════════════════════════════════


class SandboxExecutorArtifactTest(unittest.TestCase):
    def setUp(self) -> None:
        config = SandboxConfig(
            whitelist_files=frozenset({"data/sandbox/**"}),
            whitelist_dirs=frozenset({"data/sandbox/**"}),
            whitelist_modules=frozenset({"json", "math", "pathlib"}),
            whitelist_builtins=frozenset(
                {
                    "len", "print", "range", "int", "str", "list",
                    "dict", "set", "tuple", "float", "bool",
                }
            ),
            blacklist_files=frozenset(),
            blacklist_dirs=frozenset(),
            blacklist_modules=frozenset({"os", "sys", "subprocess"}),
            blacklist_builtins=frozenset({"exec", "eval", "compile", "__import__"}),
        )
        self.policy = AccessPolicy(config)
        from src.brain.sandbox.inspector import CodeInspector
        from src.brain.sandbox.executor import SandboxExecutor

        self.inspector = CodeInspector(self.policy)
        self.executor = SandboxExecutor(self.policy, self.inspector)

    def test_artifact_via_file_write(self) -> None:
        """通过 write_file 在执行目录写文件，collect_artifacts 应收集到。"""
        from src.config import Config

        # 模拟执行目录下有产物文件
        exec_dir = Config.SANDBOX_TEMP_DIR / "test-artifact-dir"
        exec_dir.mkdir(parents=True, exist_ok=True)
        (exec_dir / "result.csv").write_text("a,b\n1,2", encoding="utf-8")
        (exec_dir / "script.py").write_text("pass", encoding="utf-8")

        output_dir = Config.SANDBOX_OUTPUT_DIR / "test-artifact-output"
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            artifacts = self.executor._collect_artifacts(exec_dir, output_dir)
            names = [p.name for p in artifacts]
            self.assertIn("result.csv", names)
            # script.py 不应出现在产物中
            self.assertNotIn("script.py", names)
            # 产物已移动到 output_dir
            self.assertTrue((output_dir / "result.csv").exists())
        finally:
            import shutil
            shutil.rmtree(exec_dir, ignore_errors=True)
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_disk_space_check_passes(self) -> None:
        self.assertTrue(self.executor._check_disk_space(min_mb=1))

    def test_collect_artifacts_empty_dir(self) -> None:
        """空执行目录应返回空列表。"""
        from src.config import Config

        exec_dir = Config.SANDBOX_TEMP_DIR / "test-empty-artifact"
        exec_dir.mkdir(parents=True, exist_ok=True)
        output_dir = Config.SANDBOX_OUTPUT_DIR / "test-empty-output"
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            artifacts = self.executor._collect_artifacts(exec_dir, output_dir)
            self.assertEqual(artifacts, [])
        finally:
            import shutil
            shutil.rmtree(exec_dir, ignore_errors=True)
            shutil.rmtree(output_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════
# 端到端集成测试：创建 → 安全分析 → 执行 → 结果写入
# ═══════════════════════════════════════════════════════════════


class SandboxEndToEndTest(unittest.TestCase):
    """完整流程测试：SandboxManager 创建 → 代码安全检查 → 执行 → 结果验证。"""

    def setUp(self) -> None:
        self.manager = SandboxManager()

    def test_e2e_safe_computation(self) -> None:
        """安全数学计算：创建 → 检查通过 → 执行成功 → 输出正确。"""
        code = textwrap.dedent("""\
            result = sum(i**2 for i in range(10))
            print(f"sum={result}")
        """)

        async def run() -> None:
            result = await self.manager.execute(code, "e2e-calc")
            self.assertTrue(result.success, f"Error: {result.error}")
            self.assertIn("sum=285", result.output)
            self.assertGreater(result.execution_time, 0)
            self.assertIsNone(result.error)

        asyncio.run(run())

    def test_e2e_dangerous_rejected_before_execution(self) -> None:
        """危险代码应在安全检查阶段被拒绝，不会实际执行。"""
        code = 'import os\nos.system("echo PWNED")'

        async def run() -> None:
            result = await self.manager.execute(code, "e2e-danger")
            self.assertFalse(result.success)
            self.assertIn("安全违规", result.error)
            # 不应有输出（未执行）
            self.assertEqual(result.output, "")

        asyncio.run(run())

    def test_e2e_syntax_error_rejected(self) -> None:
        """语法错误应在解析阶段被拒绝。"""
        async def run() -> None:
            result = await self.manager.execute("def f(\n", "e2e-syntax")
            self.assertFalse(result.success)
            self.assertIn("语法错误", result.error)

        asyncio.run(run())

    def test_e2e_invalid_session_id_rejected(self) -> None:
        """非法 session_id 应在最前面被拒绝。"""
        async def run() -> None:
            result = await self.manager.execute('print("x")', "../escape")
            self.assertFalse(result.success)
            self.assertIn("非法字符", result.error)

        asyncio.run(run())

    def test_e2e_context_injected_and_used(self) -> None:
        """context 注入 → 代码中可访问注入变量。"""
        async def run() -> None:
            result = await self.manager.execute(
                'print(f"user={user}, score={score}")',
                "e2e-ctx",
                context={"user": "Alice", "score": 95.5},
            )
            self.assertTrue(result.success, f"Error: {result.error}")
            self.assertIn("user=Alice", result.output)
            self.assertIn("score=95.5", result.output)

        asyncio.run(run())

    def test_e2e_callback_receives_result(self) -> None:
        """on_result 回调接收完整 SandboxResult。"""
        received: list[SandboxResult] = []

        def cb(r: SandboxResult) -> None:
            received.append(r)

        async def run() -> None:
            await self.manager.execute('print("callback test")', "e2e-cb", on_result=cb)

        asyncio.run(run())
        self.assertEqual(len(received), 1)
        self.assertTrue(received[0].success)
        self.assertIn("callback test", received[0].output)

    def test_e2e_multiple_sequential_executions(self) -> None:
        """连续多次执行不同代码，结果互不干扰。"""
        async def run() -> None:
            r1 = await self.manager.execute('print("first")', "e2e-seq-1")
            r2 = await self.manager.execute('print("second")', "e2e-seq-2")
            r3 = await self.manager.execute('print("third")', "e2e-seq-3")
            self.assertTrue(r1.success)
            self.assertIn("first", r1.output)
            self.assertTrue(r2.success)
            self.assertIn("second", r2.output)
            self.assertTrue(r3.success)
            self.assertIn("third", r3.output)

        asyncio.run(run())
