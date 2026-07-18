from __future__ import annotations

import ast
from pathlib import Path

import pytest

_LAYER_RULES = {
    "contracts": frozenset({"contracts"}),
    "utils": frozenset({"utils"}),
    "kernel": frozenset({"contracts", "utils", "kernel"}),
    "ai": frozenset({"contracts", "utils", "ai"}),
    "platform": frozenset({"contracts", "utils", "platform"}),
    "agents": frozenset({"contracts", "utils", "agents"}),
    "localhost": frozenset({"contracts", "utils", "kernel", "ai", "platform", "agents", "localhost"}),
    "dashboard": frozenset({"contracts", "utils", "localhost", "dashboard"}),
}
_MAX_SOURCE_LINES = 500


def _src_targets(node: ast.Import | ast.ImportFrom, path: Path, source_root: Path) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        names = tuple(alias.name for alias in node.names)
    elif node.level == 0:
        names = (node.module,) if node.module is not None else ()
    else:
        package = ("src", *path.relative_to(source_root).parent.parts)
        base = package[: len(package) - node.level + 1]
        suffix = tuple(node.module.split(".")) if node.module else ()
        names = (".".join((*base, *suffix)),)
    targets = []
    for name in names:
        parts = name.split(".")
        if len(parts) > 1 and parts[0] == "src":
            targets.append(parts[1])
    return tuple(targets)


@pytest.mark.parametrize("package", tuple(_LAYER_RULES))
def test_source_packages_follow_the_one_way_dependency_rule(package: str) -> None:
    source_root = Path(__file__).parents[1] / "src"
    package_root = source_root / package
    violations: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            violations.extend(
                f"{path.relative_to(package_root)}:{node.lineno} -> src.{target}"
                for target in _src_targets(node, path, source_root)
                if target not in _LAYER_RULES[package]
            )
    assert not violations, "forbidden package dependencies:\n" + "\n".join(violations)


def test_configuration_has_no_import_time_reload_facade() -> None:
    source_root = Path(__file__).parents[1] / "src"
    assert not (source_root / "config.py").exists()
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                continue
            function = node.value.func
            is_config_reload = (
                isinstance(function, ast.Attribute)
                and function.attr == "reload"
                and isinstance(function.value, ast.Name)
                and function.value.id == "Config"
            )
            assert not is_config_reload, f"import-time Config.reload() is forbidden: {path}"


def test_source_files_stay_within_the_reviewable_size_limit() -> None:
    source_root = Path(__file__).parents[1] / "src"
    oversized = {}
    for path in source_root.rglob("*.py"):
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > _MAX_SOURCE_LINES:
            oversized[str(path.relative_to(source_root))] = line_count
    assert not oversized, f"split source files over 500 lines by responsibility: {oversized}"
