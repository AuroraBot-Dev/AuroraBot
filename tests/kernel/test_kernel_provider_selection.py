"""能力登记必须服从优先级裁决，不能被名称顺序或提前准备抢占。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from aurora_bot.contracts.kernel import ContributionKey
from aurora_bot.kernel import BuiltinSource, compose, compose_managed, module
from aurora_bot.memory_model.rules import RuleMemoryPolicy
from tests.ai.learning_support import _config
from tests.kernel.support import NoConfigSettings as _Settings
from tests.support.model import TemplateModel as FakeModel

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_bot.contracts.pkgs.memory import MemoryPolicy
    from aurora_bot.kernel import ModuleContext


class Alpha:
    """不同实例让测试能识别实际提供者。"""


class Beta:
    """部分替换时仍需保留的另一项能力。"""


class Missing:
    """未启用提供者的无关依赖不应阻止获胜模块启动。"""


def test_priority_winner_is_the_actual_instance_and_losing_pure_provider_never_runs() -> None:
    """低优先级名称排在前，解析结果仍必须决定实际实例。"""
    expected = Alpha()

    @module(name="aaa_low", provides="alpha", requires="missing")
    def low(context: ModuleContext) -> Alpha:
        """无贡献且所有能力被替换的模块不应运行。"""
        raise AssertionError("低优先级实现不应构造")

    @module(name="zzz_high", provides="alpha", priority=10)
    def high(context: ModuleContext) -> Alpha:
        """获胜实现提供可核对的确定实例。"""
        assert context.is_provider("alpha")
        return expected

    assembly = compose(_Settings(), (low, high))
    assert assembly.get("alpha") is expected


def test_partial_capability_replacement_preserves_other_ports_and_contributions() -> None:
    """较低模块可先构造独立能力，但不能提前占有已被替换的端口。"""
    key = ContributionKey[str]("test:contribution/values")
    expected, retained = Alpha(), Beta()

    @module(name="aaa_partial", provides=("alpha", "beta"), contributes=key, declares=key)
    def partial(context: ModuleContext) -> None:
        """独立 Beta 不需要等 Alpha 构造，显式登记也必须受裁决约束。"""
        assert not context.is_provider("alpha")
        assert context.is_provider("beta")
        context.provide("alpha", Alpha())
        context.provide("beta", retained)
        context.contribute(key, "保留的贡献")

    @module(name="zzz_high", provides="alpha", requires="beta", priority=10)
    def high(context: ModuleContext) -> Alpha:
        """获胜实现可以依赖较低模块中没有被替换的独立能力。"""
        assert context.get("beta") is retained
        return expected

    assembly = compose(_Settings(), (partial, high))
    assert assembly.get("alpha") is expected
    assert assembly.get("beta") is retained
    assert assembly.contributions(key) == ("保留的贡献",)


def test_self_requirement_reads_the_selected_external_provider_before_building_an_adapter() -> None:
    """模块以自身端口构造适配能力时，自依赖会跟随实际胜出的外部提供者。"""
    key = ContributionKey[Alpha]("test:contribution/adapters")
    expected = Alpha()

    @module(name="aaa_adapter", provides=("alpha", "beta"), requires="alpha", contributes=key, declares=key)
    def adapter(context: ModuleContext) -> None:
        """替换后依赖全局有效端口，避免为低优先级私有实例接线。"""
        context.contribute(key, context.get("alpha"))
        context.provide("beta", Beta())

    @module(name="zzz_high", provides="alpha", priority=10)
    def high(context: ModuleContext) -> Alpha:
        """提供当前选择的能力。"""
        return expected

    assembly = compose(_Settings(), (adapter, high))
    assert assembly.contributions(key) == (expected,)


def test_prepare_activation_and_close_share_the_same_provider_selection() -> None:
    """低优先级准备钩子先运行时也不能抢占端口，生命周期视图保持一致。"""
    key = ContributionKey[str]("test:contribution/lifecycle")
    expected = Alpha()
    observed: list[bool] = []

    async def prepare_low(context: ModuleContext) -> None:
        """贡献仍然有效，提前准备的候选实例必须被忽略。"""
        observed.append(context.is_provider("alpha"))
        context.provide("alpha", Alpha())

    async def prepare_high(context: ModuleContext) -> None:
        """实际提供者在准备阶段就可登记选中的实例。"""
        assert context.is_provider("alpha")
        context.provide("alpha", expected)

    async def verify_low(context: ModuleContext) -> None:
        """激活和关闭都看到同一获胜端口，而非模块私有候选。"""
        assert not context.is_provider("alpha")
        assert context.get("alpha") is expected

    @module(
        name="aaa_low",
        provides="alpha",
        contributes=key,
        declares=key,
        prepare=prepare_low,
        activate=verify_low,
        close=verify_low,
    )
    def low(context: ModuleContext) -> Alpha:
        """生成贡献不等于拥有能力登记权。"""
        context.contribute(key, "低优先级贡献")
        return Alpha()

    @module(name="zzz_high", provides="alpha", priority=10, prepare=prepare_high)
    def high(context: ModuleContext) -> Alpha:
        """构造阶段复用同一准备实例。"""
        return expected

    async def scenario() -> None:
        handle = await compose_managed(_Settings(), (low, high))
        try:
            await handle.activate(asyncio.Event())
            assert handle.assembly.get("alpha") is expected
            assert handle.assembly.contributions(key) == ("低优先级贡献",)
        finally:
            await handle.close()

    asyncio.run(scenario())
    assert observed == [False]


@pytest.mark.parametrize("managed", [False, True])
def test_replacing_memory_policy_does_not_load_the_unselected_builtin_weights(
    configured_project: Path, *, managed: bool
) -> None:
    """真实内建模块保留检查点服务和资源贡献，但不准备被替换的模型。"""
    config = _config(configured_project, "memory", weights="missing-builtin-weights.pt")
    expected = RuleMemoryPolicy()

    @module(name="zzz_custom_memory", provides="memory.policy", priority=10)
    def custom(context: ModuleContext) -> MemoryPolicy:
        """提供实际选择的完整策略实例。"""
        assert context.is_provider("memory.policy")
        return expected

    specs = (*BuiltinSource().discover(), custom)

    async def scenario() -> None:
        handle = await compose_managed(config, specs, instances=(("ai", FakeModel()),)) if managed else None
        assembly = handle.assembly if handle is not None else compose(config, specs, instances=(("ai", FakeModel()),))
        try:
            assert assembly.get("memory.policy") is expected
            assert assembly.get("resources").resolve(expected.ref).ref == expected.ref
            assert not (configured_project / "data/artifacts").exists()
        finally:
            if handle is not None:
                await handle.close()

    asyncio.run(scenario())
