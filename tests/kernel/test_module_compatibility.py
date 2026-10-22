"""模组兼容约束在任何准备或构造之前统一生效。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from aurora_bot.contracts.module_manifest import ModuleManifest
from aurora_bot.kernel import KERNEL_API_VERSION, ModuleSpec, compose, compose_managed, module, resolve
from tests.kernel.support import Settings as _Settings

if TYPE_CHECKING:
    from aurora_bot.kernel import ModuleContext


def test_release_version_and_supported_api_are_independent() -> None:
    """模组可以独立发布较高版本，同时继续针对当前内核 API。"""
    manifest = ModuleManifest("v9.2.0", ">=1.0, <2")
    assert manifest.version == "9.2.0"
    assert manifest.accepts(KERNEL_API_VERSION)
    assert not manifest.accepts("0.9")
    assert not manifest.accepts("2.0")
    assert replace(manifest, version="99.0").accepts(KERNEL_API_VERSION)


@pytest.mark.parametrize("version", ["", " 1", "1 ", "latest", True, None])
def test_invalid_release_versions_fail_at_declaration(version: object) -> None:
    """版本不能被隐式转换或当作可变别名。"""
    with pytest.raises(ValueError, match="模组"):
        ModuleManifest(cast("str", version))


@pytest.mark.parametrize("api", ["", " ", " >=1", "1", "^1", True, None])
def test_invalid_api_ranges_fail_at_declaration(api: object) -> None:
    """声明使用标准范围语法，空范围不能被解释成无限兼容。"""
    with pytest.raises(ValueError, match="模组"):
        ModuleManifest(kernel_api=cast("str", api))


@pytest.mark.parametrize("managed", [False, True])
def test_incompatible_module_fails_before_any_prepare_or_constructor(managed: bool) -> None:
    """即使兼容模组排在前面，也不会先产生准备或构造副作用。"""
    trace: list[str] = []

    async def prepare(context: ModuleContext) -> None:
        """准备钩子用可观察调用证明未提前运行。"""
        del context
        trace.append("prepare")

    @module(name="first", provides="str", prepare=prepare)
    def first(context: ModuleContext) -> str:
        """同步构造同样必须等待兼容检查。"""
        del context
        trace.append("construct")
        return "ready"

    @module(name="future", provides="int", manifest=ModuleManifest("3.1", ">=2,<3"))
    def future(context: ModuleContext) -> int:
        """不兼容模组不会被静默跳过或执行。"""
        del context
        trace.append("future")
        return 1

    with pytest.raises(ValueError, match=r"future.*3.1.*不兼容"):
        if managed:
            asyncio.run(compose_managed(_Settings(), (first, future)))
        else:
            compose(_Settings(), (first, future))
    assert trace == []


@pytest.mark.parametrize("mode", ["optional", "replaced"])
def test_optional_or_replaced_declarations_cannot_hide_incompatible_api(mode: str) -> None:
    """依赖筛选与优先级裁决之前就验证 SDK 契约。"""
    obsolete = ModuleSpec(
        "obsolete",
        provides=("str",),
        requires=("int",) if mode == "optional" else (),
        optional=mode == "optional",
        manifest=ModuleManifest("0.1", "<1"),
    )
    replacement = ModuleSpec("replacement", provides=("str",), priority=10)
    with pytest.raises(ValueError, match=r"obsolete.*不兼容"):
        resolve((obsolete, replacement))


def test_compose_keeps_the_exact_manifest_in_the_frozen_assembly() -> None:
    """兼容模组成功装配，清单随实际声明提供给后续能力发现。"""
    manifest = ModuleManifest("2.4", ">=1,<2")

    @module(name="compatible", provides="str", manifest=manifest)
    def compatible(context: ModuleContext) -> str:
        """构造期可以读取同一份声明清单。"""
        assert context.modules[0].manifest is manifest
        return "selected"

    assembly = compose(_Settings(), (compatible,))
    assert assembly.get("str") == "selected"
    assert assembly.modules[0].manifest is manifest


def test_module_spec_rejects_an_unvalidated_manifest() -> None:
    """外部发现来源不能用任意对象替代版本声明。"""
    with pytest.raises(TypeError, match="ModuleManifest"):
        ModuleSpec("invalid", provides=("str",), manifest=cast("ModuleManifest", {}))
