"""模块声明：``ModuleSpec`` 与把构造器登记为模块的 ``@module`` 装饰器。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from functools import wraps
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from src.contracts.identity import is_path
from src.contracts.module_manifest import DEFAULT_MODULE_MANIFEST, ModuleManifest
from src.contracts.resource import ResourceDescriptor, ResourceKey
from src.contracts.scope import ScopeDeclaration
from src.kernel.manifest import freeze_module
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
    owns_scopes: tuple[str, ...] = ()
    observes_scopes: tuple[str, ...] = ()
    scopes: tuple[ScopeDeclaration, ...] = ()
    resources: tuple[ResourceDescriptor, ...] = ()
    priority: int = 0
    optional: bool = False
    order: tuple[Ordering, ...] = ()
    hooks: Mapping[Phase, PhaseHook] = field(default_factory=dict)
    manifest: ModuleManifest = DEFAULT_MODULE_MANIFEST
    content: bytes = field(init=False, repr=False)
    resource: ResourceDescriptor = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """冻结声明容器，完整域声明也同时表达该模块的所有权。"""
        for attribute in (
            "provides",
            "requires",
            "contributes",
            "consumes",
            "declares",
            "owns_scopes",
            "observes_scopes",
            "scopes",
            "resources",
            "order",
        ):
            object.__setattr__(self, attribute, tuple(getattr(self, attribute)))
        object.__setattr__(self, "hooks", MappingProxyType(dict(self.hooks)))
        self._validate_metadata()
        patterns = tuple(scope.pattern for scope in self.scopes)
        if len(self.owns_scopes) != len(set(self.owns_scopes)) or len(patterns) != len(set(patterns)):
            raise ValueError(f"模块重复声明域：{self.name}")
        if not self.name.strip():
            raise ValueError("模块名称不能为空")
        if not any((self.provides, self.contributes, self.hooks, self.scopes, self.resources)):
            raise ValueError(f"模块既不提供能力也不贡献值：{self.name}")
        contribution_names = [key.name for key in (*self.contributes, *self.consumes)]
        if len(contribution_names) != len(set(contribution_names)):
            raise ValueError(f"模块重复声明贡献点：{self.name}")
        scopes = (*self.owned_scopes, *self.observes_scopes)
        if any(not scope.strip() or scope != scope.strip() for scope in scopes):
            raise ValueError(f"模块声明的域必须是非空且无首尾空白的文本：{self.name}")
        if len(scopes) != len(set(scopes)):
            raise ValueError(f"模块重复声明域：{self.name}")
        content, resource = freeze_module(self)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "resource", resource)

    def _validate_metadata(self) -> None:
        """声明式元数据必须是公共值对象，不能把未校验字典带入解析阶段。"""
        if not isinstance(self.manifest, ModuleManifest):
            raise TypeError("模块清单必须使用 ModuleManifest")
        if not isinstance(self.name, str) or not is_path(self.name):
            raise ValueError("模块名称必须是合法的局部资源路径")
        if any(not isinstance(scope, ScopeDeclaration) for scope in self.scopes):
            raise TypeError("模块的完整域声明必须使用 ScopeDeclaration")
        if any(not isinstance(resource, ResourceDescriptor) for resource in self.resources):
            raise TypeError("模块的资源定义必须使用 ResourceDescriptor")

    @property
    def key(self) -> ResourceKey:
        """模组本身也是命名空间下的资源，局部同名不再产生全局冲突。"""
        return ResourceKey(self.manifest.namespace, "kernel", "module", self.name)

    @property
    def module_id(self) -> str:
        """解析、登记权与生命周期共同使用完整身份。"""
        return str(self.key)

    @property
    def owned_scopes(self) -> tuple[str, ...]:
        """从声明推导所有权，不另存会在复制或替换声明后过期的模式列表。"""
        return tuple(dict.fromkeys((*self.owns_scopes, *(scope.pattern for scope in self.scopes))))

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
    manifest: ModuleManifest = DEFAULT_MODULE_MANIFEST,
    provides: type | tuple[type, ...] = (),
    requires: type | tuple[type, ...] = (),
    contributes: ContributionKey[Any] | tuple[ContributionKey[Any], ...] = (),
    consumes: ContributionKey[Any] | tuple[ContributionKey[Any], ...] = (),
    declares: ContributionKey[Any] | tuple[ContributionKey[Any], ...] = (),
    owns_scopes: str | tuple[str, ...] = (),
    observes_scopes: str | tuple[str, ...] = (),
    scopes: ScopeDeclaration | tuple[ScopeDeclaration, ...] = (),
    resources: ResourceDescriptor | tuple[ResourceDescriptor, ...] = (),
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
        @wraps(builder)
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
            manifest=manifest,
            provides=provided,
            requires=_as_tuple(requires),
            contributes=_as_tuple(contributes),
            consumes=_as_tuple(consumes),
            declares=_as_tuple(declares),
            owns_scopes=_as_tuple(owns_scopes),
            observes_scopes=_as_tuple(observes_scopes),
            scopes=_as_tuple(scopes),
            resources=_as_tuple(resources),
            priority=priority,
            optional=optional,
            order=extra_order,
            hooks=collected,
        )

    return decorator
