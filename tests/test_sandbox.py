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


import asyncio


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
