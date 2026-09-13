"""确定性发现一个已安装内部包中的直接子模块。"""

from __future__ import annotations

from importlib import import_module
from pkgutil import iter_modules
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from types import ModuleType


def discover_module_names(search_paths: Iterable[str]) -> tuple[str, ...]:
    """按文件名排序返回包内直接子模块名，不导入模块本身。"""
    return tuple(sorted(item.name for item in iter_modules(search_paths) if not item.name.startswith("_")))


def discover_modules(package_name: str, search_paths: Iterable[str]) -> tuple[ModuleType, ...]:
    """按文件名排序导入包内直接子模块，不扫描外部 entry point。"""
    return tuple(import_module(f"{package_name}.{name}") for name in discover_module_names(search_paths))
