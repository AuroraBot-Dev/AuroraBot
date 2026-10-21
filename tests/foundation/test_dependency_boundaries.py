from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from aurora_cli.configs import config_specs
from tests import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_ROOT = PROJECT_ROOT
_FRAMEWORK = _ROOT / "src" / "aurora_bot"
_CLI = _ROOT / "src" / "aurora_cli"
_LEAF_PACKAGES = frozenset({"contracts", "utils"})
_MECHANISM_PACKAGES = frozenset({"kernel", "runtime"})
_TYPE_ONLY_SRC: dict[str, set[str]] = {}


def _base_allowed(package: str) -> set[str]:
    """按约定推导一个框架包运行时可依赖的框架包集合。

    叶子包只依赖自身；其他包可依赖 contracts 与 utils；机制包额外可依赖 kernel。
    新增能力包无需修改本文件。
    """
    if package in _LEAF_PACKAGES:
        return {f"aurora_bot.{package}"}
    allowed = {f"aurora_bot.{package}", "aurora_bot.contracts", "aurora_bot.utils"}
    if package in _MECHANISM_PACKAGES:
        allowed.add("aurora_bot.kernel")
    return allowed


def test_src_packages_only_reach_capabilities_through_type_checking() -> None:
    """功能包运行时只能依赖 contracts/utils/自身；跨包能力只允许 TYPE_CHECKING。

    每个包的 ``module.py`` 是组合元数据，额外允许引用 ``aurora_bot.kernel`` 声明自身。
    """
    violations: list[str] = []
    for path in _FRAMEWORK.rglob("*.py"):
        package = path.relative_to(_FRAMEWORK).parts[0]
        base = _base_allowed(package)
        if path.name == "module.py":
            base = base | {"aurora_bot.kernel"}
        type_only = base | _TYPE_ONLY_SRC.get(package, frozenset())
        for module, guarded in _imports_of(path):
            if module in {"aurora_cli", "ops"} or module.startswith(("aurora_cli.", "ops.")):
                violations.append(f"{path.relative_to(_ROOT)} imports {module}")
            if not module.startswith("aurora_bot.") or _src_package(module) == f"aurora_bot.{package}":
                continue
            allowed = type_only if guarded else base
            if _src_package(module) not in {_src_package(item) for item in allowed}:
                tag = "typecheck" if guarded else "runtime"
                violations.append(f"{path.relative_to(_ROOT)} {tag} imports {module}")
    assert violations == []


def test_each_project_toml_has_one_registered_config_module() -> None:
    toml_names = {path.stem for path in (_CLI / "configs").glob("*/*.toml") if path.parent.name == path.stem}
    module_names = {path.stem for path in (_CLI / "configs").glob("*/*.py") if path.parent.name == path.stem}
    specs = config_specs()
    registered_names = {spec.name for spec in specs}

    assert toml_names == module_names == registered_names
    assert len(specs) == len(registered_names)
    assert {spec.path for spec in specs} == {f"config/{name}.toml" for name in registered_names}


def test_runtime_core_does_not_store_unrelated_capabilities() -> None:
    """门面只依赖实际调用的能力，避免为接线或观察转存其他模块。"""
    path = _FRAMEWORK / "runtime" / "core.py"
    unrelated = {"aurora_bot.cadence", "aurora_bot.memory", "aurora_bot.mcp"}

    assert not {_src_package(module) for module, _ in _imports_of(path)} & unrelated


def test_cli_main_only_dispatches_through_command_layer() -> None:
    path = _CLI / "main.py"
    aurora_imports = {
        module
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if (module := _imported_module(node)).startswith("aurora_cli.")
    }
    assert aurora_imports == {"aurora_cli.commander"}


def _imports_of(path: Path) -> list[tuple[str, bool]]:
    """返回文件内 (模块名, 是否处于 TYPE_CHECKING 守卫) 的导入序列。"""
    found: list[tuple[str, bool]] = []

    def walk(node: ast.AST, guarded: bool) -> None:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if module := _imported_module(node):
                found.append((module, guarded))
            return
        if isinstance(node, ast.If) and _is_type_check_test(node.test):
            for child in node.body:
                walk(child, True)
            for child in node.orelse:
                walk(child, False)
            return
        for child in ast.iter_child_nodes(node):
            walk(child, guarded)

    walk(ast.parse(path.read_text(encoding="utf-8")), False)
    return found


def _is_type_check_test(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    if isinstance(node, ast.Attribute):
        return node.attr == "TYPE_CHECKING"
    return False


def _imported_module(node: ast.AST) -> str:
    if isinstance(node, ast.ImportFrom):
        return node.module or ""
    if isinstance(node, ast.Import) and node.names:
        return node.names[0].name
    return ""


def _src_package(module: str) -> str:
    parts = module.split(".")
    return ".".join(parts[:2])


def test_generic_kernel_has_no_bot_or_cli_dependency() -> None:
    violations = [
        f"{path.relative_to(_ROOT)} imports {module}"
        for path in (_ROOT / "src" / "aurora_kernel").rglob("*.py")
        for module, _ in _imports_of(path)
        if module.split(".")[0] in {"aurora_bot", "aurora_cli"}
    ]
    assert violations == []
