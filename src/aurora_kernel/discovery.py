"""从 Python 包、目录和安装入口读取声明；不预设业务包。"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from importlib import import_module, invalidate_caches
from importlib.metadata import entry_points
from pathlib import Path
from pkgutil import iter_modules
from typing import TYPE_CHECKING, Any, Protocol

from aurora_kernel.declaration import ModuleSpec, Namespace

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from types import ModuleType

_MODULE_FILE = "module.py"
_ENTRY_POINT_GROUP = "aurora_module"


class DiscoverySource(Protocol):
    """提供一个或多个模块声明的发现源。"""

    def discover(self) -> Iterable[Any]: ...


class StaticSource:
    """直接给定模块声明；用于测试与宿主显式组装。"""

    def __init__(self, specs: Iterable[Any]) -> None:
        self._specs = tuple(specs)

    def discover(self) -> Iterable[Any]:
        return self._specs


class PackageSource:
    """扫描包内声明；默认读取子目录的 module.py，也可读取直接子模块。"""

    def __init__(self, package: str, *, extract: Callable | None = None, entry_module: str | None = "module") -> None:
        self._package = package
        self._extract = extract or module_spec
        self._entry_module = entry_module

    def discover(self) -> Iterable[Any]:
        package = import_module(self._package)
        specs: list[Any] = []
        if self._entry_module is None:
            names = sorted(item.name for item in iter_modules(package.__path__) if not item.name.startswith("_"))
            for name in names:
                origin = f"{self._package}.{name}"
                specs.append(self._extract(import_module(origin), origin))
            return specs
        for root in sorted({Path(path).resolve() for path in package.__path__}):
            if not root.is_dir():
                continue
            for directory in sorted(root.iterdir()):
                if not directory.is_dir() or directory.name.startswith(("_", ".")):
                    continue
                if not (directory / f"{self._entry_module}.py").is_file():
                    continue
                origin = f"{self._package}.{directory.name}.{self._entry_module}"
                specs.append(self._extract(import_module(origin), origin))
        return specs


class DirectorySource:
    """扫描本地插件目录；每个 ``*.py`` 或含 ``module.py`` 的子目录是一个插件。"""

    def __init__(self, directory: Path, *, extract: Callable | None = None) -> None:
        self._directory = directory
        self._extract = extract or module_spec

    def discover(self) -> Iterable[Any]:
        if not self._directory.is_dir():
            return ()
        specs: list[Any] = []
        for path in sorted(self._directory.iterdir()):
            if path.name.startswith(("_", ".")):
                continue
            if path.is_file() and path.suffix == ".py":
                specs.append(self._extract(_load_file(path, path.stem), str(path)))
            elif path.is_dir() and (path / _MODULE_FILE).is_file():
                module_file = path / _MODULE_FILE
                specs.append(self._extract(_load_file(module_file, path.name, package=True), str(module_file)))
        return specs


class EntryPointSource:
    """读取安装入口组，每个入口指向声明或导出 MODULE 的模块。"""

    def __init__(self, group: str = _ENTRY_POINT_GROUP, *, extract: Callable | None = None) -> None:
        self._group = group
        self._extract = extract or module_spec

    def discover(self) -> Iterable[Any]:
        specs: list[Any] = []
        for entry_point in sorted(entry_points(group=self._group), key=lambda item: item.name):
            specs.append(self._extract(entry_point.load(), f"{self._group}:{entry_point.name}"))
        return specs


def _load_file(path: Path, name: str, *, package: bool = False) -> ModuleType:
    """目录入口具有包上下文，重新发现时只清理该插件拥有的导入缓存。"""
    identity = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
    module_name = f"aurora_module_{name}_{identity}"
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


def module_spec(source: object, origin: str) -> ModuleSpec:
    candidate = getattr(source, "MODULE", source)
    if isinstance(candidate, Namespace):
        return candidate.spec
    if not isinstance(candidate, ModuleSpec):
        raise TypeError(f"模块来源必须导出唯一 MODULE：{origin}")
    return candidate
