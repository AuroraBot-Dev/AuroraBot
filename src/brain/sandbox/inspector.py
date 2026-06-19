"""Sandbox AST 安全检查器。

基于 Python 标准库 ast 模块，在代码执行前检测危险操作。
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, ClassVar

from src.brain.sandbox.base import SecurityViolation
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.brain.sandbox.policy import AccessPolicy, AccessPolicySnapshot

logger = get_logger("CodeInspector")


class CodeInspector:
    """基于 Python AST 的代码安全检查器。"""

    # 构造函数 → 返回类型的映射（用于调用链解析）
    _CONSTRUCTOR_TO_CLASS: ClassVar[dict[str, str]] = {
        # pathlib concrete paths
        "Path": "pathlib.Path",
        "PosixPath": "pathlib.PosixPath",
        "WindowsPath": "pathlib.WindowsPath",
        # pathlib pure paths
        "PurePath": "pathlib.PurePath",
        "PurePosixPath": "pathlib.PurePosixPath",
        "PureWindowsPath": "pathlib.PureWindowsPath",
    }

    _DANGEROUS_NODE_TYPES: ClassVar[dict[str, str]] = {
        "Delete": "禁止删除操作（del 语句）",
        "Global": "禁止 global 变量声明",
        "Nonlocal": "禁止 nonlocal 变量声明",
    }

    _DANGEROUS_CALLS: ClassVar[dict[str, str]] = {
        "exec": "禁止调用 exec()",
        "eval": "禁止调用 eval()",
        "compile": "禁止调用 compile()",
        "__import__": "禁止调用 __import__()",
        "globals": "禁止访问 globals()",
        "locals": "禁止访问 locals()",
        "breakpoint": "禁止调用 breakpoint()",
        "exit": "禁止调用 exit()",
        "quit": "禁止调用 quit()",
        "os.remove": "禁止调用 os.remove()",
        "os.unlink": "禁止调用 os.unlink()",
        "os.rmdir": "禁止调用 os.rmdir()",
        "os.removedirs": "禁止调用 os.removedirs()",
        "os.rename": "禁止调用 os.rename()",
        "os.renames": "禁止调用 os.renames()",
        "shutil.rmtree": "禁止调用 shutil.rmtree()",
        "shutil.move": "禁止调用 shutil.move()",
        # pathlib.Path 方法（通过前缀匹配覆盖所有变体）
        "pathlib.Path.unlink": "禁止调用 Path.unlink()",
        "pathlib.Path.rmdir": "禁止调用 Path.rmdir()",
        "pathlib.Path.rename": "禁止调用 Path.rename()",
        "pathlib.Path.replace": "禁止调用 Path.replace()",
        "pathlib.Path.symlink_to": "禁止调用 Path.symlink_to()（可创建符号链接绕过路径检查）",
        "pathlib.Path.hardlink_to": "禁止调用 Path.hardlink_to()（可创建硬链接）",
        # 其他危险调用
        "str.format": "禁止调用 str.format()（可利用 {0.__class__.__bases__} 进行属性遍历逃逸）",
        "operator.attrgetter": "禁止调用 operator.attrgetter()（可动态访问 __class__ 等内部属性）",
        "gc.get_objects": "禁止调用 gc.get_objects()（可遍历所有 Python 对象进行逃逸）",
        "gc.get_referrers": "禁止调用 gc.get_referrers()（可获取引用链进行逃逸）",
        "inspect.currentframe": "禁止调用 inspect.currentframe()（可获取当前帧对象进行逃逸）",
        "inspect.getouterframes": "禁止调用 inspect.getouterframes()（可遍历调用栈进行逃逸）",
        "inspect.getmembers": "禁止调用 inspect.getmembers()（可遍历对象所有成员进行逃逸）",
        "linecache.getline": "禁止调用 linecache.getline()（可按文件名读取任意源码文件）",
        "linecache.getlines": "禁止调用 linecache.getlines()（可按文件名读取任意源码文件全部内容）",
        "traceback.extract_stack": "禁止调用 traceback.extract_stack()（可泄露调用栈信息）",
        "traceback.format_stack": "禁止调用 traceback.format_stack()（可泄露调用栈信息）",
    }

    # 危险调用的前缀匹配规则（用于覆盖类继承体系）
    _DANGEROUS_CALL_PREFIXES: ClassVar[dict[str, str]] = {
        "pathlib.Path.": "pathlib.Path 方法禁止调用",
        "pathlib.PosixPath.": "pathlib.PosixPath 方法禁止调用",
        "pathlib.WindowsPath.": "pathlib.WindowsPath 方法禁止调用",
        "pathlib.PurePath.": "pathlib.PurePath 方法禁止调用",
        "pathlib.PurePosixPath.": "pathlib.PurePosixPath 方法禁止调用",
        "pathlib.PureWindowsPath.": "pathlib.PureWindowsPath 方法禁止调用",
    }

    _DANGEROUS_ATTRS: ClassVar[dict[str, str]] = {
        "__subclasses__": "禁止访问 __subclasses__()",
        "__bases__": "禁止访问 __bases__",
        "__mro__": "禁止访问 __mro__",
        "__code__": "禁止访问 __code__",
        "__globals__": "禁止访问 __globals__",
        "__builtins__": "禁止访问 __builtins__",
        "__getattribute__": "禁止访问 __getattribute__()（可动态访问任意内部属性，如 __class__）",
        "__class__": "禁止访问 __class__（属性遍历逃逸入口）",
        "__reduce__": "禁止访问 __reduce__()（可触发 pickle 序列化进行对象重建逃逸）",
        "__reduce_ex__": "禁止访问 __reduce_ex__()（可触发 pickle 序列化）",
        "__getstate__": "禁止访问 __getstate__()（可访问对象内部状态）",
        "__setstate__": "禁止访问 __setstate__()（可设置对象内部状态绕过检查）",
        "__closure__": "禁止访问 __closure__()（可访问函数闭包变量）",
        "__func__": "禁止访问 __func__()（可访问函数内部实现）",
        "__self__": "禁止访问 __self__()（可访问绑定方法的实例）",
        "__dict__": "禁止访问 __dict__（可获取对象内部字典）",
        "__init__": "禁止访问 __init__（可获取构造方法进行对象重建）",
        "__new__": "禁止访问 __new__（可绕过 __init__ 构造对象）",
        "__call__": "禁止访问 __call__（可获取可调用对象引用）",
        "__wrapped__": "禁止访问 __wrapped__（可获取被装饰函数的原始实现）",
    }

    def __init__(self, policy: AccessPolicy) -> None:
        """初始化检查器，绑定 AccessPolicy 用于 import 和 open 白名单判断。"""
        self._policy = policy

    def inspect(self, code: str, policy_snapshot: AccessPolicySnapshot | None = None) -> list[SecurityViolation]:
        """对代码进行完整的 AST 安全检查。违规列表为空表示安全通过。

        policy_snapshot 用于单次执行期间保持配置一致性，
        若传入则使用快照中的白/黑名单，否则使用 self._policy 的当前配置。
        """
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []

        violations: list[SecurityViolation] = []
        violations.extend(self._check_dangerous_nodes(tree))
        violations.extend(self._check_imports(tree, policy_snapshot))
        violations.extend(self._check_calls(tree))
        violations.extend(self._check_open_calls(tree, policy_snapshot))
        violations.extend(self._check_attr_access(tree))
        violations.extend(self._check_type_introspection(tree))

        if violations:
            logger.warning(f"安全检查发现 {len(violations)} 个违规")
            for v in violations:
                logger.debug(f"  违规: {v.violation_type} - {v.detail}")
        return violations

    def _check_dangerous_nodes(self, tree: ast.Module) -> list[SecurityViolation]:
        """检查危险的 AST 节点类型（Delete, Global, Nonlocal）。"""
        violations = []
        for node in ast.walk(tree):
            node_type = type(node).__name__
            if node_type in self._DANGEROUS_NODE_TYPES:
                violations.append(
                    SecurityViolation(
                        violation_type="dangerous_operation",
                        detail=self._DANGEROUS_NODE_TYPES[node_type],
                        line=getattr(node, "lineno", None),
                        node_name=node_type,
                    )
                )
        return violations

    def _check_imports(self, tree: ast.Module, snapshot: AccessPolicySnapshot | None = None) -> list[SecurityViolation]:  # noqa: ARG002
        """检查所有 import 语句。"""
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                violations.extend(
                    SecurityViolation(
                        violation_type="blacklisted_access",
                        detail=f"禁止 import {alias.name}",
                        line=node.lineno,
                        node_name="Import",
                    )
                    for alias in node.names
                    if not self._policy.can_import_module(alias.name)
                )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if not self._policy.can_import_module(module):
                    imported_names = ", ".join(alias.name for alias in node.names)
                    violations.append(
                        SecurityViolation(
                            violation_type="blacklisted_access",
                            detail=f"禁止 from {module} import {imported_names}",
                            line=node.lineno,
                            node_name="ImportFrom",
                        )
                    )
        return violations

    def _resolve_call_chain(self, node: ast.expr) -> str | None:
        """解析调用链，如 os.path.join → 'os.path.join'。

        支持解析：
        - 简单名称：os → 'os'
        - 属性链：os.path.join → 'os.path.join'
        - 字面量方法：'str'.format() → 'str.format'
        - 构造函数：Path('x').unlink() → 'pathlib.Path.unlink'
        """
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = self._resolve_call_chain(node.value)
            if parent is not None:
                return f"{parent}.{node.attr}"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return "str"
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                # 使用构造函数映射表，而非硬编码
                if func.id in self._CONSTRUCTOR_TO_CLASS:
                    return self._CONSTRUCTOR_TO_CLASS[func.id]
            elif isinstance(func, ast.Attribute):
                chain = self._resolve_call_chain(func)
                if chain:
                    return chain
        return None

    def _check_calls(self, tree: ast.Module) -> list[SecurityViolation]:
        """检查所有函数调用，验证是否调用危险函数。

        支持两种匹配方式：
        1. 精确匹配：chain in _DANGEROUS_CALLS
        2. 前缀匹配：检查 _DANGEROUS_CALL_PREFIXES
        """
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            chain = self._resolve_call_chain(node.func)
            if chain is None:
                continue

            # 精确匹配
            if chain in self._DANGEROUS_CALLS:
                violations.append(
                    SecurityViolation(
                        violation_type="dangerous_operation",
                        detail=self._DANGEROUS_CALLS[chain],
                        line=node.lineno,
                        node_name="Call",
                    )
                )
                continue

            # 前缀匹配（用于类继承体系）
            for prefix, msg in self._DANGEROUS_CALL_PREFIXES.items():
                if chain.startswith(prefix):
                    violations.append(
                        SecurityViolation(
                            violation_type="dangerous_operation",
                            detail=f"{msg}: {chain[len(prefix) :]}",
                            line=node.lineno,
                            node_name="Call",
                        )
                    )
                    break
        return violations

    def _check_open_calls(
        self,
        tree: ast.Module,
        snapshot: AccessPolicySnapshot | None = None,  # noqa: ARG002
    ) -> list[SecurityViolation]:
        """检查 open() 调用，提取路径参数交由 AccessPolicy 判断。"""
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = self._resolve_call_chain(node.func)
            if func_name != "open":
                continue
            if not node.args:
                continue
            path_arg = node.args[0]
            if not isinstance(path_arg, ast.Constant) or not isinstance(path_arg.value, str):
                violations.append(
                    SecurityViolation(
                        violation_type="whitelist_denied",
                        detail="open() 路径参数必须是字符串字面量",
                        line=node.lineno,
                        node_name="Call",
                    )
                )
                continue
            from pathlib import Path

            mode = "r"
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                mode = str(node.args[1].value)
            if not self._policy.can_open_file(Path(path_arg.value), mode):
                violations.append(
                    SecurityViolation(
                        violation_type="whitelist_denied",
                        detail=f'禁止 open("{path_arg.value}", "{mode}")',
                        line=node.lineno,
                        node_name="Call",
                    )
                )
        return violations

    def _check_attr_access(self, tree: ast.Module) -> list[SecurityViolation]:
        """检查危险的属性访问（如 __subclasses__）。"""
        return [
            SecurityViolation(
                violation_type="dangerous_operation",
                detail=self._DANGEROUS_ATTRS[node.attr],
                line=getattr(node, "lineno", None),
                node_name="Attribute",
            )
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in self._DANGEROUS_ATTRS
        ]

    def _check_type_introspection(self, tree: ast.Module) -> list[SecurityViolation]:
        """检查 type() 返回值的属性访问（类型内省逃逸）。"""
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            value = node.value
            if not isinstance(value, ast.Call):
                continue
            func = value.func
            if isinstance(func, ast.Name) and func.id == "type":
                violations.append(
                    SecurityViolation(
                        violation_type="dangerous_operation",
                        detail=f"type() 返回值不允许属性访问: .{node.attr}",
                        line=getattr(node, "lineno", None),
                        node_name="Attribute",
                    )
                )
        return violations
