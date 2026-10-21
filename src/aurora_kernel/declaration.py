"""与业务无关的模块声明；名称用于寻址，普通函数承载行为。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from aurora_kernel.phase import CONSTRUCT, Ordering, Phase

type AsyncCleanup = Callable[[], Awaitable[None]]


def check_name(name: str) -> None:
    """名称必须明确；不从 Python 类型或目录结构推导业务身份。"""
    if not isinstance(name, str) or not name or any(character.isspace() for character in name):
        raise ValueError("名称必须是非空且不含空白的字符串")


@dataclass(frozen=True, slots=True)
class Manifest:
    version: str = "1.0.0"
    kernel_api: str = ">=1,<2"

    def __post_init__(self) -> None:
        Version(self.version)
        SpecifierSet(self.kernel_api)

    def accepts(self, version: str) -> bool:
        return Version(version) in SpecifierSet(self.kernel_api)


@dataclass(frozen=True, slots=True)
class Callpoint:
    name: str
    mode: str = "single"

    def __post_init__(self) -> None:
        check_name(self.name)
        if self.mode not in {"single", "collect", "notify"}:
            raise ValueError(f"调用点模式无效：{self.mode}")


@dataclass(frozen=True, slots=True)
class Hook:
    target: str
    callback: Callable[..., Any]
    priority: int = 0

    def __post_init__(self) -> None:
        check_name(self.target)
        if not callable(self.callback):
            raise TypeError("调用点实现必须可调用")


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    module_id: str
    depends: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    contributes: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    declares: tuple[str, ...] = ()
    priority: int = 0
    optional: bool = False
    order: tuple[Ordering, ...] = ()
    hooks: Mapping[Phase, Callable[..., Any]] = field(default_factory=dict)
    points: tuple[Callpoint, ...] = ()
    handlers: tuple[Hook, ...] = ()
    manifest: Manifest = field(default_factory=Manifest)

    def __post_init__(self) -> None:
        check_name(self.module_id)
        for attribute in (
            "depends",
            "provides",
            "requires",
            "contributes",
            "consumes",
            "declares",
            "order",
            "points",
            "handlers",
        ):
            object.__setattr__(self, attribute, tuple(getattr(self, attribute)))
        for name in (*self.depends, *self.provides, *self.requires, *self.contributes, *self.consumes, *self.declares):
            check_name(name)
        object.__setattr__(self, "hooks", MappingProxyType(dict(self.hooks)))
        if any(not callable(callback) for callback in self.hooks.values()):
            raise TypeError("生命周期钩子必须可调用")

    def hook(self, phase: Phase) -> Callable[..., Any] | None:
        return self.hooks.get(phase)

    def participates(self, phase: Phase) -> bool:
        return phase in self.hooks


class Namespace:
    """装饰器只收集声明；每次宿主构建都会取得独立的冻结声明与 ctx。"""

    def __init__(self, spec: ModuleSpec) -> None:
        self.spec = spec

    @property
    def name(self) -> str:
        return self.spec.module_id

    def on(self, phase: Phase) -> Callable:
        """登记一个生命周期钩子。"""

        def register(callback: Callable) -> Callable:
            if phase in self.spec.hooks:
                raise ValueError(f"生命周期钩子重复：{self.name}/{phase.name}")
            self.spec = replace(self.spec, hooks={**self.spec.hooks, phase: callback})
            return callback

        return register

    def declare(self, name: str, *, mode: str = "single") -> str:
        """声明调用点，由本模块或其他模块登记实现。"""
        target = f"{self.name}:{name}"
        point = Callpoint(target, mode)
        self.spec = replace(self.spec, points=(*self.spec.points, point))
        return target

    def hook(self, target: str, *, priority: int = 0) -> Callable:
        """登记调用点实现；不同命名空间可以实现同一调用点。"""

        def register(callback: Callable) -> Callable:
            self.spec = replace(self.spec, handlers=(*self.spec.handlers, Hook(target, callback, priority)))
            return callback

        return register

    def callpoint(self, name: str, *, mode: str = "single", priority: int = 0) -> Callable:
        """同时声明调用点并登记这个函数为实现。"""
        return self.hook(self.declare(name, mode=mode), priority=priority)


def namespace(name: str, *, requires: tuple[str, ...] = (), version: str = "1.0.0") -> Callable[[Callable], Namespace]:
    """把初始化函数注册为命名空间；requires 是其他命名空间的名称。"""

    def register(callback: Callable) -> Namespace:
        return Namespace(
            ModuleSpec(
                name,
                depends=requires,
                hooks={CONSTRUCT: callback},
                manifest=Manifest(version),
            )
        )

    return register
