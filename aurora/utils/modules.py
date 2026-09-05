"""确定性发现一个已安装内部包中的直接子模块。"""

from __future__ import annotations

from importlib import import_module
from pkgutil import iter_modules
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from types import ModuleType


def discover_modules(package_name: str, search_paths: Iterable[str]) -> tuple[ModuleType, ...]:
    """按文件名排序导入包内直接子模块，不扫描外部 entry point。"""
    names = sorted(item.name for item in iter_modules(search_paths) if not item.name.startswith("_"))
    return tuple(import_module(f"{package_name}.{name}") for name in names)
