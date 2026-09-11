"""模块声明：``ModuleSpec`` 与把构造器登记为模块的 ``@module`` 装饰器。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncio

    from src.contracts import ContributionKey
    from src.kernel.context import ModuleContext

type AsyncCleanup = Callable[[], Awaitable[None]]
type ModuleRegistrar = Callable[["ModuleContext"], None]
type ModulePrepare = Callable[["ModuleContext"], Awaitable[AsyncCleanup | None]]
type ModuleHook = Callable[["ModuleContext"], Awaitable[None]]
type ModuleRunner = Callable[["ModuleContext", "asyncio.Event"], Coroutine[Any, Any, None]]
type ModuleBuilder = Callable[["ModuleContext"], object]


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    """一个自描述模块：提供什么契约、需要什么契约、如何构造与何时激活。"""

    name: str
    provides: tuple[type, ...] = ()
    requires: tuple[type, ...] = ()
    contributes: tuple[ContributionKey[Any], ...] = ()
    consumes: tuple[ContributionKey[Any], ...] = ()
    register: ModuleRegistrar | None = None
    priority: int = 0
    optional: bool = False
    activation_after: tuple[type, ...] = ()
    prepare: ModulePrepare | None = None
    activate: ModuleHook | None = None
    run: ModuleRunner | None = None
    close: ModuleHook | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("模块名称不能为空")
        if not self.provides and not self.contributes and self.register is None:
            raise ValueError(f"模块既不提供能力也不贡献值：{self.name}")
        contribution_names = [key.name for key in (*self.contributes, *self.consumes)]
        if len(contribution_names) != len(set(contribution_names)):
            raise ValueError(f"模块重复声明贡献点：{self.name}")


def _as_tuple[T](value: T | tuple[T, ...] | None) -> tuple[T, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    return (value,)


def module(
    *,
    name: str,
    provides: type | tuple[type, ...] = (),
    requires: type | tuple[type, ...] = (),
    contributes: ContributionKey[Any] | tuple[ContributionKey[Any], ...] = (),
    consumes: ContributionKey[Any] | tuple[ContributionKey[Any], ...] = (),
    priority: int = 0,
    optional: bool = False,
    activation_after: type | tuple[type, ...] = (),
    prepare: ModulePrepare | None = None,
    activate: ModuleHook | None = None,
    run: ModuleRunner | None = None,
    close: ModuleHook | None = None,
) -> Callable[[ModuleBuilder], ModuleSpec]:
    """把 ``build(context) -> instance`` 构造器登记为 ``ModuleSpec``。

    构造器返回的实例会登记到全部 ``provides`` 契约下；需要显式登记多个不同实例的模块
    直接构造 ``ModuleSpec`` 并提供 ``register``。构造器返回 ``None`` 表示不做自动登记。
    """

    provided = _as_tuple(provides)

    def decorator(builder: ModuleBuilder) -> ModuleSpec:
        def register(context: ModuleContext) -> None:
            instance = builder(context)
            if instance is None:
                return
            for capability in provided:
                if not context.contains(capability):
                    context.provide(capability, instance)

        return ModuleSpec(
            name=name,
            provides=provided,
            requires=_as_tuple(requires),
            contributes=_as_tuple(contributes),
            consumes=_as_tuple(consumes),
            register=register,
            priority=priority,
            optional=optional,
            activation_after=_as_tuple(activation_after),
            prepare=prepare,
            activate=activate,
            run=run,
            close=close,
        )

    return decorator
