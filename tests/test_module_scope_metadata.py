"""域类型在模块构造前可发现，合并不会让通用规则吞掉运行台账。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from aurorabot.contracts.scope import ScopeCatalog, ScopeDeclaration, ScopeKind, merge_scope_catalog
from aurorabot.kernel import PREPARE, ModuleSpec, compose, compose_managed, module
from tests.kernel_support import NoConfigSettings as _Settings

if TYPE_CHECKING:
    from aurorabot.kernel import ModuleContext


def test_full_scope_metadata_is_visible_before_any_module_is_constructed() -> None:
    """只读声明足以构造域目录，无需依赖业务模块的运行期贡献。"""
    declaration = ScopeDeclaration("lab:world/jobs/*", ScopeKind.RUN, "异步过程的投递台账")
    trace: list[str] = []

    async def prepare(context: ModuleContext) -> None:
        """准备阶段可以读取尚未构造的另一个模块声明。"""
        declarations = tuple(scope for spec in context.modules for scope in spec.scopes)
        assert declarations == (declaration,)
        assert not trace

    @module(name="observer", provides=int, prepare=prepare)
    def observer(context: ModuleContext) -> int:
        """普通构造仍在准备完成之后。"""
        return 1

    @module(name="producer", provides=str, scopes=declaration)
    def producer(context: ModuleContext) -> str:
        """域目录读取不应提前运行生产者。"""
        trace.append("constructed")
        return "ready"

    async def scenario() -> None:
        handle = await compose_managed(_Settings(), (observer, producer))
        try:
            assert handle.assembly.modules == (observer, producer)
            assert producer.owned_scopes == (declaration.pattern,)
        finally:
            await handle.close()

    asyncio.run(scenario())
    assert trace == ["constructed"]
    assert compose(_Settings(), (producer,)).modules == (producer,)


def test_replacing_a_spec_keeps_domain_metadata_and_freezes_original_hook_mapping() -> None:
    """发现源调整优先级不会重复域声明，外部字典也不能改写已发布阶段。"""

    async def prepare(context: ModuleContext) -> None:
        """用于核对阶段身份的实际回调。"""

    declaration = ScopeDeclaration("lab:world/jobs/*", ScopeKind.RUN, "过程台账")
    hooks = {PREPARE: prepare}
    spec = ModuleSpec("producer", provides=(str,), scopes=(declaration,), hooks=hooks)
    hooks.clear()
    copied = replace(spec, priority=10)
    assert copied.scopes == spec.scopes
    assert copied.owned_scopes == (declaration.pattern,)
    changed = replace(spec, scopes=(replace(declaration, pattern="lab:world/new/*"),))
    assert changed.owned_scopes == ("lab:world/new/*",)
    assert spec.hook(PREPARE) is prepare
    with pytest.raises(TypeError):
        cast("dict[object, object]", spec.hooks)[PREPARE] = prepare


def test_specific_module_domains_precede_generic_configuration_fallbacks() -> None:
    """具体的业务与运行子域各自生效，名称较长的命名空间不改变路径具体度。"""
    defaults = (
        ScopeDeclaration("*:world/bot/*", ScopeKind.RESOURCE, "主体状态"),
        ScopeDeclaration("*:world/bot/*/operations", ScopeKind.RUN, "操作台账"),
    )
    configured = ScopeCatalog((ScopeDeclaration("long_namespace:world/*", ScopeKind.RESOURCE, "通用世界"),))
    catalog = merge_scope_catalog(configured, defaults)
    assert catalog.classify("long_namespace:world/bot/a/operations") is ScopeKind.RUN
    assert catalog.describe("long_namespace:world/bot/a") == "主体状态"
    assert catalog.describe("long_namespace:world/room") == "通用世界"


def test_same_pattern_config_overrides_default_and_conflicting_module_definitions_fail() -> None:
    """显式配置可调整既有模式，两个模组不能为同一模式声明不同语义。"""
    default = ScopeDeclaration("lab:world/jobs/*", ScopeKind.RUN, "过程台账")
    override = ScopeDeclaration(default.pattern, ScopeKind.RESOURCE, "明确选择可自动召回")
    catalog = merge_scope_catalog(ScopeCatalog((override,)), (default, default))
    assert catalog.declarations == (override,)
    with pytest.raises(ValueError, match="域模式定义不一致"):
        merge_scope_catalog(ScopeCatalog(()), (default, override))
