"""模块声明：``ModuleSpec`` 与把构造器登记为模块的 ``@module`` 装饰器。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.kernel.phase import ACTIVATE, CLOSE, CONSTRUCT, DRAIN, PREPARE, READY, RUN, Ordering, Phase

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
type PhaseHook = ModuleRegistrar | ModulePrepare | ModuleHook | ModuleRunner


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    """一个自描述模块：提供什么契约、需要什么契约、在哪些运行阶段参与。"""

    name: str
    provides: tuple[type, ...] = ()
    requires: tuple[type, ...] = ()
    contributes: tuple[ContributionKey[Any], ...] = ()
    consumes: tuple[ContributionKey[Any], ...] = ()
    declares: tuple[ContributionKey[Any], ...] = ()
    priority: int = 0
    optional: bool = False
    order: tuple[Ordering, ...] = ()
    hooks: Mapping[Phase, PhaseHook] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("模块名称不能为空")
        if not self.provides and not self.contributes and not self.hooks:
            raise ValueError(f"模块既不提供能力也不贡献值：{self.name}")
        contribution_names = [key.name for key in (*self.contributes, *self.consumes)]
        if len(contribution_names) != len(set(contribution_names)):
            raise ValueError(f"模块重复声明贡献点：{self.name}")

    def hook(self, phase: Phase) -> PhaseHook | None:
        """返回本模块在该阶段注册的钩子；未参与返回 ``None``。"""
        return self.hooks.get(phase)

    def participates(self, phase: Phase) -> bool:
        return phase in self.hooks


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
    declares: ContributionKey[Any] | tuple[ContributionKey[Any], ...] = (),
    priority: int = 0,
    optional: bool = False,
    activation_after: type | tuple[type, ...] = (),
    order: Ordering | tuple[Ordering, ...] = (),
    prepare: ModulePrepare | None = None,
    activate: ModuleHook | None = None,
    ready: ModuleHook | None = None,
    run: ModuleRunner | None = None,
    drain: ModuleHook | None = None,
    close: ModuleHook | None = None,
    hooks: Mapping[Phase, PhaseHook] | None = None,
) -> Callable[[ModuleBuilder], ModuleSpec]:
    """把 ``build(context) -> instance`` 构造器登记为 ``ModuleSpec``。

    具名参数是内置阶段的便捷写法；``hooks`` 可声明任意阶段（含自定义阶段）的钩子。
    构造器返回的实例会登记到全部 ``provides`` 契约下；返回 ``None`` 表示不做自动登记。
    """

    provided = _as_tuple(provides)
    extra_order = _as_tuple(order)
    if activation_after:
        extra_order = (*extra_order, Ordering(ACTIVATE, after=_as_tuple(activation_after), after_phase=ACTIVATE))
    named_hooks = ((PREPARE, prepare), (ACTIVATE, activate), (READY, ready), (RUN, run), (DRAIN, drain), (CLOSE, close))

    def decorator(builder: ModuleBuilder) -> ModuleSpec:
        def register(context: ModuleContext) -> None:
            instance = builder(context)
            if instance is None:
                return
            for capability in provided:
                if not context.contains(capability):
                    context.provide(capability, instance)

        collected: dict[Phase, PhaseHook] = dict(hooks or {})
        for phase, hook in named_hooks:
            if hook is not None:
                collected[phase] = hook
        collected[CONSTRUCT] = register

        return ModuleSpec(
            name=name,
            provides=provided,
            requires=_as_tuple(requires),
            contributes=_as_tuple(contributes),
            consumes=_as_tuple(consumes),
            declares=_as_tuple(declares),
            priority=priority,
            optional=optional,
            order=extra_order,
            hooks=collected,
        )

    return decorator
