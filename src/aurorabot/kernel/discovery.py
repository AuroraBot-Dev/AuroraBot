"""模块发现源：内置 ``aurorabot`` 包、本地插件目录与 ``aurorabot_plugin`` entry point。"""

from __future__ import annotations

import importlib.util
import sys
from importlib import import_module, invalidate_caches
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from aurorabot.kernel.declaration import ModuleSpec

if TYPE_CHECKING:
    from collections.abc import Iterable
    from types import ModuleType

_MODULE_FILE = "module.py"
_ENTRY_POINT_GROUP = "aurorabot_plugin"


class DiscoverySource(Protocol):
    """提供一个或多个模块声明的发现源。"""

    def discover(self) -> Iterable[ModuleSpec]: ...


class StaticSource:
    """直接给定模块声明；用于测试与宿主显式组装。"""

    def __init__(self, specs: Iterable[ModuleSpec]) -> None:
        self._specs = tuple(specs)

    def discover(self) -> Iterable[ModuleSpec]:
        return self._specs


class BuiltinSource:
    """扫描随 AuroraBot 安装的 ``aurorabot`` 功能包，读取每个包的 ``module.py``。"""

    def __init__(self, package: str = "aurorabot") -> None:
        self._package = package

    def discover(self) -> Iterable[ModuleSpec]:
        package = import_module(self._package)
        specs: list[ModuleSpec] = []
        for root in sorted({Path(path).resolve() for path in package.__path__}):
            if not root.is_dir():
                continue
            for directory in sorted(root.iterdir()):
                if not directory.is_dir() or directory.name.startswith(("_", ".")):
                    continue
                if not (directory / _MODULE_FILE).is_file():
                    continue
                module = import_module(f"{self._package}.{directory.name}.module")
                specs.append(_module_spec(module, f"{self._package}.{directory.name}.module"))
        return specs


class DirectorySource:
    """扫描本地插件目录；每个 ``*.py`` 或含 ``module.py`` 的子目录是一个插件。"""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def discover(self) -> Iterable[ModuleSpec]:
        if not self._directory.is_dir():
            return ()
        specs: list[ModuleSpec] = []
        for path in sorted(self._directory.iterdir()):
            if path.name.startswith(("_", ".")):
                continue
            if path.is_file() and path.suffix == ".py":
                specs.append(_module_spec(_load_file(path, path.stem), str(path)))
            elif path.is_dir() and (path / _MODULE_FILE).is_file():
                module_file = path / _MODULE_FILE
                specs.append(_module_spec(_load_file(module_file, path.name, package=True), str(module_file)))
        return specs


class EntryPointSource:
    """读取 ``aurorabot_plugin`` entry point 组，每个入口指向一个 ``ModuleSpec``。"""

    def __init__(self, group: str = _ENTRY_POINT_GROUP) -> None:
        self._group = group

    def discover(self) -> Iterable[ModuleSpec]:
        specs: list[ModuleSpec] = []
        for entry_point in sorted(entry_points(group=self._group), key=lambda item: item.name):
            specs.append(_module_spec(entry_point.load(), f"{self._group}:{entry_point.name}"))
        return specs


def _load_file(path: Path, name: str, *, package: bool = False) -> ModuleType:
    """目录入口具有包上下文，重新发现时只清理该插件拥有的导入缓存。"""
    module_name = f"aurorabot_plugin_{'package' if package else 'file'}_{name}"
    search = [str(path.parent)] if package else None
    spec = importlib.util.spec_from_file_location(module_name, path, submodule_search_locations=search)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载插件：{path}")
    _drop_modules(module_name)
    invalidate_caches()
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        _drop_modules(module_name)
        raise
    return module


def _drop_modules(module_name: str) -> None:
    """相对导入产生的子模块与入口一起清理，不触及其他插件。"""
    for name in tuple(sys.modules):
        if name == module_name or name.startswith(f"{module_name}."):
            del sys.modules[name]


def _module_spec(source: object, origin: str) -> ModuleSpec:
    candidate = getattr(source, "MODULE", None)
    if not isinstance(candidate, ModuleSpec):
        raise TypeError(f"模块来源必须导出唯一 MODULE：{origin}")
    return candidate
