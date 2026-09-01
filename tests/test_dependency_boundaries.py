from __future__ import annotations

import ast
from pathlib import Path

from aurora.composition import COMPOSITION_SPECS
from aurora.configuration import CONFIG_SPECS
from ops.registry import iter_operations

_ROOT = Path(__file__).parents[1]
_ALLOWED_SRC_IMPORTS = {
    "utils": frozenset({"src.utils"}),
    "contracts": frozenset({"src.contracts"}),
    "agents": frozenset({"src.agents", "src.contracts", "src.utils"}),
    "prompt": frozenset({"src.contracts", "src.prompt"}),
    "tools": frozenset({"src.agents", "src.contracts", "src.tools", "src.utils"}),
    "ai": frozenset({"src.ai", "src.contracts", "src.utils"}),
    "console": frozenset({"src.console", "src.contracts", "src.utils"}),
    "cadence": frozenset({"src.cadence", "src.contracts", "src.utils"}),
    "engine": frozenset({"src.agents", "src.contracts", "src.engine", "src.prompt", "src.tools", "src.utils"}),
    "memory": frozenset({"src.contracts", "src.memory", "src.utils"}),
    "mcp": frozenset({"src.contracts", "src.mcp", "src.utils"}),
    "world": frozenset({"src.contracts", "src.utils", "src.world"}),
}
_REMOVED_PACKAGES = ("apps", "config", "platform", "sandbox")


def test_src_dependency_direction_matches_minimal_architecture() -> None:
    violations: list[str] = []
    for path in (_ROOT / "src").rglob("*.py"):
        package = path.relative_to(_ROOT / "src").parts[0]
        allowed = _ALLOWED_SRC_IMPORTS[package]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            module = _imported_module(node)
            if module in {"aurora", "ops"} or module.startswith(("aurora.", "ops.")):
                violations.append(f"{path.relative_to(_ROOT)} imports {module}")
            if module.startswith("src.") and _src_package(module) not in allowed:
                violations.append(f"{path.relative_to(_ROOT)} imports {module}")
    assert violations == []


def test_ops_depends_on_neither_composition_root_nor_src() -> None:
    violations: list[str] = []
    for path in (_ROOT / "ops").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            module = _imported_module(node)
            if module in {"aurora", "src"} or module.startswith(("aurora.", "src.")):
                violations.append(f"{path.relative_to(_ROOT)} imports {module}")
    assert violations == []


def test_removed_src_subpackages_do_not_return_as_empty_scaffolding() -> None:
    existing = [name for name in _REMOVED_PACKAGES if (_ROOT / "src" / name).exists()]
    assert existing == []


def test_project_configuration_does_not_construct_src_objects() -> None:
    violations: list[str] = []
    for path in (_ROOT / "aurora" / "configuration").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            module = _imported_module(node)
            if module == "src" or module.startswith("src."):
                violations.append(f"{path.relative_to(_ROOT)} imports {module}")
    assert violations == []


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


def test_each_composition_module_targets_a_src_package_and_is_registered() -> None:
    module_names = {path.stem for path in (_ROOT / "aurora" / "composition").glob("*.py") if path.stem != "__init__"}
    src_names = {path.name for path in (_ROOT / "src").iterdir() if path.is_dir() and not path.name.startswith("__")}
    registered_names = {spec.register.__module__.rsplit(".", maxsplit=1)[-1] for spec in COMPOSITION_SPECS}

    assert module_names == registered_names
    assert module_names <= src_names


def test_each_ops_operation_module_contributes_to_registered_catalog() -> None:
    module_names = {path.stem for path in (_ROOT / "ops" / "operations").glob("*.py") if path.stem != "__init__"}
    registered_names = {
        spec.handler.__module__.rsplit(".", maxsplit=1)[-1] for spec in iter_operations() if spec.handler is not None
    }

    assert module_names == registered_names


def test_cli_main_only_dispatches_through_command_layer() -> None:
    path = _ROOT / "aurora" / "main.py"
    aurora_imports = {
        module
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if (module := _imported_module(node)).startswith("aurora.")
    }
    assert aurora_imports == {"aurora.commands", "aurora.commander"}


def _imported_module(node: ast.AST) -> str:
    if isinstance(node, ast.ImportFrom):
        return node.module or ""
    if isinstance(node, ast.Import) and node.names:
        return node.names[0].name
    return ""


def _src_package(module: str) -> str:
    parts = module.split(".")
    return ".".join(parts[:2])
