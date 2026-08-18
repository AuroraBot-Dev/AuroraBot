from __future__ import annotations

import ast
from pathlib import Path

from aurora.composition import COMPOSITION_REGISTRARS
from aurora.configuration import CONFIG_REGISTRARS

_ROOT = Path(__file__).parents[1]
_ALLOWED_SRC_IMPORTS = {
    "contracts": frozenset({"src.contracts"}),
    "prompt": frozenset({"src.contracts", "src.prompt"}),
    "ai": frozenset({"src.ai", "src.contracts"}),
    "engine": frozenset({"src.contracts", "src.engine", "src.prompt"}),
}
_REMOVED_PACKAGES = ("agents", "apps", "config", "console", "memory", "platform", "sandbox", "utils")


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
    registered_names = {
        register.__module__.removeprefix("aurora.configuration.").replace(".", "/") for register in CONFIG_REGISTRARS
    }

    assert toml_names == module_names == registered_names
    assert len(CONFIG_REGISTRARS) == len(registered_names)


def test_each_composition_module_targets_a_src_package_and_is_registered() -> None:
    module_names = {path.stem for path in (_ROOT / "aurora" / "composition").glob("*.py") if path.stem != "__init__"}
    src_names = {path.name for path in (_ROOT / "src").iterdir() if path.is_dir() and not path.name.startswith("__")}
    registered_names = {register.__module__.rsplit(".", maxsplit=1)[-1] for register in COMPOSITION_REGISTRARS}

    assert module_names == registered_names
    assert module_names <= src_names


def test_cli_main_only_depends_on_command_directory() -> None:
    path = _ROOT / "aurora" / "main.py"
    aurora_imports = {
        module
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if (module := _imported_module(node)).startswith("aurora.")
    }
    assert aurora_imports == {"aurora.commands"}


def _imported_module(node: ast.AST) -> str:
    if isinstance(node, ast.ImportFrom):
        return node.module or ""
    if isinstance(node, ast.Import) and node.names:
        return node.names[0].name
    return ""


def _src_package(module: str) -> str:
    parts = module.split(".")
    return ".".join(parts[:2])
