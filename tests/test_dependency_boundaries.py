from __future__ import annotations

import ast
from pathlib import Path

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
            if module == "aurora" or module.startswith("aurora."):
                violations.append(f"{path.relative_to(_ROOT)} imports {module}")
            if module.startswith("src.") and _src_package(module) not in allowed:
                violations.append(f"{path.relative_to(_ROOT)} imports {module}")
    assert violations == []


def test_removed_src_subpackages_do_not_return_as_empty_scaffolding() -> None:
    existing = [name for name in _REMOVED_PACKAGES if (_ROOT / "src" / name).exists()]
    assert existing == []


def _imported_module(node: ast.AST) -> str:
    if isinstance(node, ast.ImportFrom):
        return node.module or ""
    if isinstance(node, ast.Import) and node.names:
        return node.names[0].name
    return ""


def _src_package(module: str) -> str:
    parts = module.split(".")
    return ".".join(parts[:2])
