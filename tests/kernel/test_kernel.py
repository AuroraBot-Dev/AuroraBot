"""组合微内核的装配、冲突、可选与生命周期不变量测试。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from aurorabot.contracts import ContributionKey
from aurorabot.kernel import (
    RUN,
    DirectorySource,
    ManagedAssembly,
    ModuleSpec,
    Ordering,
    Phase,
    PhaseKind,
    StaticSource,
    compose,
    compose_managed,
    module,
    resolve,
)
from tests.kernel.support import Alpha, Beta, Gamma
from tests.kernel.support import Settings as _Settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from aurorabot.kernel.context import ModuleContext


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

    @module(name="provider.a", contributes=key, declares=key)
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


def test_ready_and_drain_run_between_activate_and_close() -> None:
    trace: list[str] = []

    async def activate(context: ModuleContext) -> None:
        del context
        trace.append("activate")

    async def ready(context: ModuleContext) -> None:
        del context
        trace.append("ready")

    async def drain(context: ModuleContext) -> None:
        del context
        trace.append("drain")

    async def close(context: ModuleContext) -> None:
        del context
        trace.append("close")

    @module(name="phased", provides=Alpha, activate=activate, ready=ready, drain=drain, close=close)
    def build_phased(context: ModuleContext) -> Alpha:
        del context
        trace.append("construct")
        return Alpha()

    async def scenario() -> None:
        stop = asyncio.Event()
        handle = await compose_managed(_Settings(), _specs(build_phased).discover())
        await handle.activate(stop)
        await handle.close()

    asyncio.run(scenario())

    assert trace == ["construct", "activate", "ready", "drain", "close"]


def test_order_constraint_orders_run_phase() -> None:
    trace: list[str] = []

    async def run_alpha(context: ModuleContext, stop: asyncio.Event) -> None:
        del context
        trace.append("alpha.run")
        await stop.wait()

    async def run_beta(context: ModuleContext, stop: asyncio.Event) -> None:
        del context
        trace.append("beta.run")
        await stop.wait()

    @module(name="alpha", provides=Alpha, requires=Beta, order=Ordering(RUN, after=(Beta,)), run=run_alpha)
    def build_alpha(context: ModuleContext) -> Alpha:
        del context
        return Alpha()

    @module(name="beta", provides=Beta, run=run_beta)
    def build_beta(context: ModuleContext) -> Beta:
        del context
        return Beta()

    async def scenario() -> None:
        stop = asyncio.Event()
        handle = await compose_managed(_Settings(), _specs(build_alpha, build_beta).discover())
        await handle.activate(stop)
        await asyncio.sleep(0)
        stop.set()
        await handle.close()

    asyncio.run(scenario())

    assert trace == ["beta.run", "alpha.run"]


def test_resolution_exposes_phase_plan() -> None:
    @module(name="alpha", provides=Alpha)
    def build_alpha(context: ModuleContext) -> Alpha:
        del context
        return Alpha()

    resolution = resolve(_specs(build_alpha).discover())

    assert [step.phase.name for step in resolution.phases] == [
        "prepare",
        "construct",
        "activate",
        "ready",
        "run",
        "drain",
        "close",
    ]


def test_undeclared_contribution_fails() -> None:
    key = ContributionKey[str]("test.undeclared")

    @module(name="provider", contributes=key)
    def provider(context: ModuleContext) -> None:
        context.contribute(key, "a")

    with pytest.raises(ValueError, match="未被任何模块声明"):
        resolve(_specs(provider).discover())


def test_duplicate_contribution_declaration_fails() -> None:
    key = ContributionKey[str]("test.duplicated")

    @module(name="a", contributes=key, declares=key)
    def a(context: ModuleContext) -> None:
        context.contribute(key, "a")

    @module(name="b", contributes=key, declares=key)
    def b(context: ModuleContext) -> None:
        context.contribute(key, "b")

    with pytest.raises(ValueError, match="被多个模块声明"):
        resolve(_specs(a, b).discover())


def test_custom_phase_hook_runs_in_order() -> None:
    trace: list[str] = []
    custom = Phase("alpha.audit", 450, PhaseKind.HOOK)

    async def audit(context: ModuleContext) -> None:
        del context
        trace.append("audit")

    @module(name="alpha", provides=Alpha, hooks={custom: audit})
    def build_alpha(context: ModuleContext) -> Alpha:
        del context
        trace.append("construct")
        return Alpha()

    async def scenario() -> None:
        stop = asyncio.Event()
        handle = await compose_managed(_Settings(), _specs(build_alpha).discover())
        await handle.activate(stop)
        await handle.close()

    asyncio.run(scenario())

    assert trace == ["construct", "audit"]


def test_construction_phase_after_runtime_phase_fails() -> None:
    late = Phase("late.build", 900, PhaseKind.BUILD)

    def late_build(context: ModuleContext) -> None:
        del context

    @module(name="alpha", provides=Alpha, hooks={late: late_build})
    def build_alpha(context: ModuleContext) -> Alpha:
        del context
        return Alpha()

    with pytest.raises(ValueError, match="构造阶段必须全部早于运行阶段"):
        resolve(_specs(build_alpha).discover())


def test_directory_source_loads_plugin_file(tmp_path: Path) -> None:
    plugin = tmp_path / "my_plugin.py"
    plugin.write_text(
        "from aurorabot.kernel import module\n\n"
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
