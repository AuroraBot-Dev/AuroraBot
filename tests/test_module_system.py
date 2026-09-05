"""通用模块发现、贡献聚合与统一生命周期的不变量测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

import pytest

from aurora import configuration as configuration_package
from aurora.composer import (
    CompositionContext,
    ContributionKey,
    InstanceKey,
    PackageSpec,
    build_module_specs,
    compose,
    compose_managed,
)
from aurora.config import assemble_config
from aurora.utils.modules import discover_modules

if TYPE_CHECKING:
    from aurora.config import AuroraConfig


def _config(tmp_path: Path) -> AuroraConfig:
    return assemble_config(tmp_path, ())


def _noop_register(context: CompositionContext) -> None:
    del context


def test_discover_modules_sorts_direct_children_and_skips_underscored() -> None:
    names = [
        module.__name__.rsplit(".", maxsplit=1)[-1]
        for module in discover_modules(
            configuration_package.__name__,
            tuple(str(path) for path in configuration_package.__path__),
        )
    ]
    directory = sorted(
        path.stem
        for path in Path(configuration_package.__file__).parent.iterdir()
        if path.is_file() and path.suffix == ".py" and not path.stem.startswith("_")
    )

    assert names == sorted(names)
    assert names == directory
    assert "__init__" not in names


def test_contribution_aggregates_ordered_values_without_central_list(tmp_path: Path) -> None:
    key = ContributionKey[str]("test.catalog")
    instance = InstanceKey[str]("consumer.instance")
    contributions: list[str] = []

    def provider_a(context: CompositionContext) -> None:
        context.contribute(key, "a")

    def provider_b(context: CompositionContext) -> None:
        context.contribute(key, "b")

    def consumer(context: CompositionContext) -> None:
        contributions.extend(context.contributions(key))
        context.provide(instance, "")

    specs = build_module_specs(
        (
            PackageSpec(
                key=InstanceKey[str]("provider.a"),
                provides=(InstanceKey[str]("provider.a"),),
                requires=(),
                register=provider_a,
                contributes=(key,),
            ),
            PackageSpec(
                key=InstanceKey[str]("provider.b"),
                provides=(InstanceKey[str]("provider.b"),),
                requires=(),
                register=provider_b,
                contributes=(key,),
            ),
            PackageSpec(
                key=instance,
                provides=(instance,),
                requires=(),
                register=consumer,
                consumes=(key,),
            ),
        )
    )
    assembly = compose(_config(tmp_path), specs)

    assert contributions == ["a", "b"]
    assert assembly.get(instance) == ""


def test_contribution_with_zero_providers_is_legal_for_consumer(tmp_path: Path) -> None:
    key = ContributionKey[str]("test.empty")
    instance = InstanceKey[str]("consumer.empty")

    def consumer(context: CompositionContext) -> None:
        context.provide(instance, str(len(context.contributions(key))))

    assembly = compose(
        _config(tmp_path),
        build_module_specs(
            (
                PackageSpec(
                    key=instance,
                    provides=(instance,),
                    requires=(),
                    register=consumer,
                    consumes=(key,),
                ),
            )
        ),
    )

    assert assembly.get(instance) == "0"


def test_lifecycle_prepares_before_construct_and_closes_reverse(tmp_path: Path) -> None:
    trace: list[str] = []
    first = InstanceKey[str]("hook.first")
    second = InstanceKey[str]("hook.second")

    async def prepare_first(context: CompositionContext) -> Callable[[], Awaitable[None]]:
        trace.append("prepare.first")
        context.provide(first, "first")

        async def cleanup_first() -> None:
            trace.append("cleanup.first")

        return cleanup_first

    async def prepare_second(context: CompositionContext) -> Callable[[], Awaitable[None]]:
        trace.append("prepare.second")
        context.provide(second, "second")

        async def cleanup_second() -> None:
            trace.append("cleanup.second")

        return cleanup_second

    specs = build_module_specs(
        (
            PackageSpec(
                key=first,
                provides=(first,),
                requires=(),
                register=_noop_register,
                prepare=prepare_first,
            ),
            PackageSpec(
                key=second,
                provides=(second,),
                requires=(first.name,),
                register=_noop_register,
                prepare=prepare_second,
            ),
        )
    )

    async def scenario() -> None:
        lifecycle = await compose_managed(_config(tmp_path), specs)
        assert trace == ["prepare.first", "prepare.second"]
        await lifecycle.close()
        assert trace == ["prepare.first", "prepare.second", "cleanup.second", "cleanup.first"]

    asyncio.run(scenario())


def test_lifecycle_activation_respects_after_order_and_stops_run_tasks(tmp_path: Path) -> None:
    trace: list[str] = []
    first = InstanceKey[str]("run.first")
    second = InstanceKey[str]("run.second")

    async def activate_first(context: CompositionContext) -> None:
        del context
        trace.append("activate.first")

    async def activate_second(context: CompositionContext) -> None:
        del context
        trace.append("activate.second")

    async def run_first(context: CompositionContext, stop: asyncio.Event) -> None:
        del context
        trace.append("run.first")
        await stop.wait()

    specs = build_module_specs(
        (
            PackageSpec(
                key=first,
                provides=(first,),
                requires=(),
                register=_noop_register,
                activation_after=(),
                activate=activate_first,
                run=run_first,
            ),
            PackageSpec(
                key=second,
                provides=(second,),
                requires=(),
                register=_noop_register,
                activation_after=(first.name,),
                activate=activate_second,
            ),
        )
    )

    async def scenario() -> None:
        stop = asyncio.Event()
        lifecycle = await compose_managed(_config(tmp_path), specs)
        await lifecycle.activate(stop)
        await asyncio.sleep(0)
        stop.set()
        await lifecycle.close()

        assert trace == ["activate.first", "activate.second", "run.first"]

    asyncio.run(scenario())


def test_lifecycle_closes_cleanups_when_construct_fails(tmp_path: Path) -> None:
    trace: list[str] = []
    good = InstanceKey[str]("fail.good")
    bad = InstanceKey[str]("fail.bad")

    async def prepare_good(context: CompositionContext) -> Callable[[], Awaitable[None]]:
        context.provide(good, "good")

        async def cleanup_good() -> None:
            trace.append("cleanup.good")

        return cleanup_good

    def failing_register(context: CompositionContext) -> None:
        del context
        raise ValueError("构造失败")

    specs = build_module_specs(
        (
            PackageSpec(
                key=good,
                provides=(good,),
                requires=(),
                register=_noop_register,
                prepare=prepare_good,
            ),
            PackageSpec(
                key=bad,
                provides=(bad,),
                requires=(),
                register=failing_register,
            ),
        )
    )

    async def scenario() -> None:
        with pytest.raises(ValueError, match="构造失败"):
            await compose_managed(_config(tmp_path), specs)
        assert trace == ["cleanup.good"]

    asyncio.run(scenario())
