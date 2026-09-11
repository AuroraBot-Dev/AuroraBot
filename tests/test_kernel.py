"""组合微内核的装配、冲突、可选与生命周期不变量测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from src.contracts import ContributionKey
from src.kernel import (
    DirectorySource,
    ManagedAssembly,
    ModuleSpec,
    StaticSource,
    compose,
    compose_managed,
    module,
    resolve,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from src.kernel.context import ModuleContext


class Alpha:
    pass


class Beta:
    pass


class Gamma:
    pass


class _Settings:
    def __init__(self, values: dict[type, object] | None = None) -> None:
        self._values = values or {}

    @property
    def project_root(self) -> Path:
        return Path()

    def get[T](self, config_type: type[T]) -> T:
        return cast("T", self._values[config_type])


def _specs(*specs: ModuleSpec) -> StaticSource:
    return StaticSource(specs)


def test_compose_injects_required_capabilities_by_dependency_order() -> None:
    @module(name="alpha", provides=Alpha)
    def build_alpha(context: ModuleContext) -> Alpha:
        del context
        return Alpha()

    @module(name="beta", provides=Beta, requires=Alpha)
    def build_beta(context: ModuleContext) -> Beta:
        assert isinstance(context.get(Alpha), Alpha)
        return Beta()

    assembly = compose(_Settings(), _specs(build_beta, build_alpha).discover())

    assert isinstance(assembly.get(Alpha), Alpha)
    assert isinstance(assembly.get(Beta), Beta)
    assert assembly.get_optional(Gamma) is None


def test_contribution_aggregates_and_consumer_depends_on_contributors() -> None:
    key = ContributionKey[str]("test.catalog")
    seen: list[str] = []

    @module(name="provider.a", contributes=key)
    def provider_a(context: ModuleContext) -> None:
        context.contribute(key, "a")

    @module(name="provider.b", contributes=key)
    def provider_b(context: ModuleContext) -> None:
        context.contribute(key, "b")

    @module(name="consumer", provides=Beta, consumes=key)
    def consumer(context: ModuleContext) -> Beta:
        seen.extend(context.contributions(key))
        return Beta()

    compose(_Settings(), _specs(consumer, provider_b, provider_a).discover())

    assert seen == ["a", "b"]


def test_priority_resolves_conflicting_providers() -> None:
    @module(name="low", provides=Alpha, priority=0)
    def low(context: ModuleContext) -> Alpha:
        del context
        return Alpha()

    @module(name="high", provides=Alpha, priority=10)
    def high(context: ModuleContext) -> Alpha:
        del context
        return Alpha()

    assembly = compose(_Settings(), _specs(low, high).discover())

    assert isinstance(assembly.get(Alpha), Alpha)


def test_same_priority_conflict_fails() -> None:
    @module(name="first", provides=Alpha)
    def first(context: ModuleContext) -> Alpha:
        del context
        return Alpha()

    @module(name="second", provides=Alpha)
    def second(context: ModuleContext) -> Alpha:
        del context
        return Alpha()

    with pytest.raises(ValueError, match="同优先级"):
        compose(_Settings(), _specs(first, second).discover())


def test_missing_required_capability_fails() -> None:
    @module(name="needs", provides=Beta, requires=Alpha)
    def needs(context: ModuleContext) -> Beta:
        del context
        return Beta()

    with pytest.raises(ValueError, match="没有提供者"):
        compose(_Settings(), _specs(needs).discover())


def test_optional_module_is_skipped_when_dependency_missing() -> None:
    @module(name="optional", provides=Beta, requires=Alpha, optional=True)
    def optional(context: ModuleContext) -> Beta:
        del context
        return Beta()

    assembly = compose(_Settings(), _specs(optional).discover())

    assert assembly.get_optional(Beta) is None


def test_cycle_dependency_fails_with_path() -> None:
    @module(name="a", provides=Alpha, requires=Beta)
    def a(context: ModuleContext) -> Alpha:
        del context
        return Alpha()

    @module(name="b", provides=Beta, requires=Alpha)
    def b(context: ModuleContext) -> Beta:
        del context
        return Beta()

    with pytest.raises(ValueError, match="循环依赖"):
        resolve(_specs(a, b).discover())


def test_one_instance_can_satisfy_multiple_contracts() -> None:
    @module(name="multi", provides=(Alpha, Beta))
    def multi(context: ModuleContext) -> Alpha:
        del context
        return Alpha()

    assembly = compose(_Settings(), _specs(multi).discover())

    assert assembly.get(Alpha) is assembly.get(Beta)


def test_managed_lifecycle_prepare_activate_run_close_order() -> None:
    trace: list[str] = []

    async def prepare(context: ModuleContext) -> Callable[[], Awaitable[None]]:
        del context
        trace.append("prepare")

        async def cleanup() -> None:
            trace.append("cleanup")

        return cleanup

    async def activate(context: ModuleContext) -> None:
        del context
        trace.append("activate")

    async def run(context: ModuleContext, stop: asyncio.Event) -> None:
        del context
        trace.append("run")
        await stop.wait()

    async def close(context: ModuleContext) -> None:
        del context
        trace.append("close")

    @module(
        name="lifecycle",
        provides=Alpha,
        prepare=prepare,
        activate=activate,
        run=run,
        close=close,
    )
    def lifecycle(context: ModuleContext) -> Alpha:
        del context
        trace.append("register")
        return Alpha()

    async def scenario() -> ManagedAssembly:
        stop = asyncio.Event()
        handle = await compose_managed(_Settings(), _specs(lifecycle).discover())
        assert trace == ["prepare", "register"]
        await handle.activate(stop)
        await asyncio.sleep(0)
        stop.set()
        await handle.close()
        return handle

    asyncio.run(scenario())

    assert trace == ["prepare", "register", "activate", "run", "close", "cleanup"]


def test_managed_lifecycle_rolls_back_when_construct_fails() -> None:
    trace: list[str] = []

    async def prepare(context: ModuleContext) -> Callable[[], Awaitable[None]]:
        del context

        async def cleanup() -> None:
            trace.append("cleanup")

        return cleanup

    @module(name="good", provides=Alpha, prepare=prepare)
    def good(context: ModuleContext) -> Alpha:
        del context
        return Alpha()

    @module(name="bad", provides=Beta, requires=Alpha)
    def bad(context: ModuleContext) -> Beta:
        del context
        raise ValueError("构造失败")

    async def scenario() -> None:
        with pytest.raises(ValueError, match="构造失败"):
            await compose_managed(_Settings(), _specs(good, bad).discover())

    asyncio.run(scenario())

    assert trace == ["cleanup"]


def test_directory_source_loads_plugin_file(tmp_path: Path) -> None:
    plugin = tmp_path / "my_plugin.py"
    plugin.write_text(
        "from src.kernel import module\n\n"
        "class Widget:\n"
        "    pass\n\n"
        "@module(name='external.alpha', provides=Widget)\n"
        "def build(context):\n"
        "    return Widget()\n\n"
        "MODULE = build\n",
        encoding="utf-8",
    )

    specs = tuple(DirectorySource(tmp_path).discover())

    assert [spec.name for spec in specs] == ["external.alpha"]
