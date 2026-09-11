from __future__ import annotations

import ast
from pathlib import Path

from aurora.configuration import CONFIG_SPECS
from ops.registry import iter_operations

_ROOT = Path(__file__).parents[1]
_SRC_BASE_ALLOWED = {
    package: {f"src.{package}", "src.contracts", "src.utils"}
    for package in (
        "agents",
        "prompt",
        "tools",
        "ai",
        "console",
        "cadence",
        "engine",
        "kernel",
        "memory",
        "mcp",
        "runtime",
        "world",
    )
}
_SRC_BASE_ALLOWED.update({"contracts": {"src.contracts"}, "utils": {"src.utils"}})
_TYPE_ONLY_SRC = {
    "runtime": {"src.kernel"},
}
_REMOVED_PACKAGES = ("apps", "config", "platform", "sandbox")


def test_src_packages_only_reach_capabilities_through_type_checking() -> None:
    """功能 src 包运行时只能依赖 contracts/utils/自身；跨包能力只允许 TYPE_CHECKING。

    每个包的 ``module.py`` 是组合元数据，额外允许引用 ``src.kernel`` 声明自身。
    """
    violations: list[str] = []
    for path in (_ROOT / "src").rglob("*.py"):
        package = path.relative_to(_ROOT / "src").parts[0]
        base = _SRC_BASE_ALLOWED[package]
        if path.name == "module.py":
            base = base | {"src.kernel"}
        type_only = base | _TYPE_ONLY_SRC.get(package, frozenset())
        for module, guarded in _imports_of(path):
            if module in {"aurora", "ops"} or module.startswith(("aurora.", "ops.")):
                violations.append(f"{path.relative_to(_ROOT)} imports {module}")
            if not module.startswith("src.") or _src_package(module) == f"src.{package}":
                continue
            allowed = type_only if guarded else base
            if _src_package(module) not in {_src_package(item) for item in allowed}:
                tag = "typecheck" if guarded else "runtime"
                violations.append(f"{path.relative_to(_ROOT)} {tag} imports {module}")
    assert violations == []


def test_ops_only_touches_leaf_infrastructure_and_assembly_types() -> None:
    """ops 作为 backend：运行时只许 import 组合内核、配置叶子与 contracts/utils。

    aurora.config/configuration 与 src.kernel/src.contracts/src.utils 是允许集；src 功能包
    不得进入 ops 的运行时导入。
    """
    aurora_runtime_allowed = ("aurora.config", "aurora.configuration")
    violations: list[str] = []
    for path in (_ROOT / "ops").rglob("*.py"):
        for module, guarded in _imports_of(path):
            if (
                module.startswith("src.")
                and not guarded
                and _src_package(module)
                not in {
                    "src.contracts",
                    "src.kernel",
                    "src.utils",
                }
            ):
                violations.append(f"{path.relative_to(_ROOT)} runtime imports {module}")
            if module in {"aurora", "src"} or module.startswith(("aurora.", "ops.operations.aurora")):
                if guarded:
                    continue
                allowed = any(module == prefix or module.startswith(f"{prefix}.") for prefix in aurora_runtime_allowed)
                if module == "aurora" or not allowed:
                    violations.append(f"{path.relative_to(_ROOT)} runtime imports {module}")
    assert violations == []


def test_removed_src_subpackages_do_not_return_as_empty_scaffolding() -> None:
    existing = [name for name in _REMOVED_PACKAGES if (_ROOT / "src" / name).exists()]
    assert existing == []


def test_each_project_toml_has_one_registered_configuration_module() -> None:
    toml_names = {
        path.relative_to(_ROOT / "config.example").with_suffix("").as_posix()
        for path in (_ROOT / "config.example").rglob("*.toml")
    }
    module_names = {
        path.relative_to(_ROOT / "aurora" / "configuration").with_suffix("").as_posix()
        for path in (_ROOT / "aurora" / "configuration").rglob("*.py")
        if path.stem != "__init__"
    }
    registered_names = {spec.name for spec in CONFIG_SPECS}

    assert toml_names == module_names == registered_names
    assert len(CONFIG_SPECS) == len(registered_names)


def test_each_ops_operation_module_contributes_to_registered_catalog() -> None:
    module_names = {path.stem for path in (_ROOT / "ops" / "operations").glob("*.py") if path.stem != "__init__"}
    registered_names = {
        spec.handler.__module__.rsplit(".", maxsplit=1)[-1] for spec in iter_operations() if spec.handler is not None
    }

    assert module_names == registered_names


def test_runtime_core_does_not_store_unrelated_capabilities() -> None:
    """门面只依赖实际调用的能力，避免为接线或观察转存其他模块。"""
    path = _ROOT / "src" / "runtime" / "core.py"
    unrelated = {"src.cadence", "src.memory", "src.mcp"}

    assert not {_src_package(module) for module, _ in _imports_of(path)} & unrelated


def test_cli_main_only_dispatches_through_command_layer() -> None:
    path = _ROOT / "aurora" / "main.py"
    aurora_imports = {
        module
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if (module := _imported_module(node)).startswith("aurora.")
    }
    assert aurora_imports == {"aurora.commands", "aurora.commander"}


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
