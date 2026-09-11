"""模块发现源：内置 ``src`` 包、本地插件目录与 ``aurorabot_plugin`` entry point。"""

from __future__ import annotations

import importlib.util
import sys
from importlib import import_module
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from src.kernel.declaration import ModuleSpec

if TYPE_CHECKING:
    from collections.abc import Iterable

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
    """扫描随 AuroraBot 安装的 ``src`` 功能包，读取每个包的 ``module.py``。"""

    def __init__(self, package: str = "src") -> None:
        self._package = package

    def discover(self) -> Iterable[ModuleSpec]:
        package = import_module(self._package)
        root = Path(package.__file__ or "").parent
        specs: list[ModuleSpec] = []
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
                specs.append(_module_spec(_load_file(module_file, f"{path.name}_module"), str(module_file)))
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


def _load_file(path: Path, name: str):
    module_name = f"aurorabot_plugin_{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载插件：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _module_spec(source: object, origin: str) -> ModuleSpec:
    candidate = getattr(source, "MODULE", None)
    if not isinstance(candidate, ModuleSpec):
        raise TypeError(f"模块来源必须导出唯一 MODULE：{origin}")
    return candidate
