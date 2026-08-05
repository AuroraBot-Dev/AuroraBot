"""RFC 0200 源码包导入边界。"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"

ALLOWED_SRC_DEPENDENCIES = {
    "contracts": {"contracts"},
    "utils": {"utils"},
    "config": {"config", "contracts"},
    "prompt": {"prompt", "contracts"},
    "engine": {"engine", "contracts", "utils"},
    "ai": {"ai", "contracts", "utils"},
    "memory": {"memory", "contracts", "utils"},
    "agents": {"agents", "prompt", "contracts", "utils"},
    "console": {"console", "contracts", "utils"},
    "platform": {"platform", "contracts", "utils"},
    "sandbox": {"sandbox", "utils"},
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_src_never_imports_process_composition() -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in SRC.rglob("*.py")
        if any(module == "aurora" or module.startswith("aurora.") for module in _imports(path))
    ]
    assert offenders == []


def test_hot_path_package_dependencies() -> None:
    offenders = []
    for package, allowed in ALLOWED_SRC_DEPENDENCIES.items():
        for path in (SRC / package).rglob("*.py"):
            for module in _imports(path):
                if not module.startswith("src."):
                    continue
                dependency = module.split(".", 2)[1]
                if dependency not in allowed:
                    offenders.append(f"{path.relative_to(ROOT).as_posix()} -> {module}")
    assert offenders == []


def test_platform_uses_contract_ports_only() -> None:
    imports = set().union(*(_imports(path) for path in (SRC / "platform").rglob("*.py")))
    assert not any(module.startswith(("src.localhost", "src.engine")) for module in imports)


def test_legacy_kernel_package_is_removed() -> None:
    assert not any((SRC / "kernel").glob("*.py"))
