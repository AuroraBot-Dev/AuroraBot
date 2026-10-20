"""局部同名模组按完整身份参与解析、登记与生命周期。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from aurorabot.contracts.module_manifest import ModuleManifest
from aurorabot.contracts.resource import ResourceKey
from aurorabot.kernel import ModuleSpec, compose, compose_managed, module, resolve
from tests.kernel.support import Settings as _Settings

if TYPE_CHECKING:
    from aurorabot.kernel import ModuleContext


def _spec(
    namespace: str,
    capability: type,
    value: object,
    trace: list[tuple[str, str]],
    requires: tuple[type, ...] = (),
) -> ModuleSpec:
    """每个独立模组都使用同一个局部名，通过命名空间表达身份。"""

    async def prepare(context: ModuleContext) -> None:
        """每项准备按自己的完整依赖关系运行。"""
        del context
        trace.append(("prepare", namespace))

    async def activate(context: ModuleContext) -> None:
        """激活阶段保留每个同名模组的参与权。"""
        assert context.is_provider(capability)
        trace.append(("activate", namespace))

    async def close(context: ModuleContext) -> None:
        """关闭和回滚不能按局部名字去重。"""
        assert context.is_provider(capability)
        trace.append(("close", namespace))

    @module(
        name="shared",
        manifest=ModuleManifest(namespace=namespace),
        provides=capability,
        requires=requires,
        prepare=prepare,
        activate=activate,
        close=close,
    )
    def build(context: ModuleContext) -> object:
        """登记权与依赖从内核实际注入的完整身份判断。"""
        assert context.is_provider(capability)
        assert all(context.contains(required) for required in requires)
        trace.append(("build", namespace))
        return value

    return build


def test_module_identity_is_native_and_independent_of_release_version() -> None:
    """命名空间和局部路径确定稳定资源名称，发布版本独立保存。"""
    spec = ModuleSpec("nested/shared", provides=(str,), manifest=ModuleManifest("2.4", namespace="lab"))
    assert spec.key == ResourceKey.parse("lab:kernel/module/nested/shared")
    assert spec.module_id == str(spec.key)
    assert replace(spec, manifest=replace(spec.manifest, version="3.0")).key == spec.key


@pytest.mark.parametrize("namespace", ["", "Lab", "lab:", "lab/team"])
def test_invalid_module_namespaces_fail_at_declaration(namespace: str) -> None:
    """非法归属不能进入依赖图后才被发现。"""
    with pytest.raises(ValueError, match="命名空间"):
        ModuleManifest(namespace=namespace)


@pytest.mark.parametrize("name", [" ", "lab:shared", "shared name", "/shared"])
def test_module_local_name_must_be_a_resource_path(name: str) -> None:
    """归属由清单声明，局部名称不夹带另一份命名空间。"""
    with pytest.raises(ValueError, match="资源路径"):
        ModuleSpec(name, provides=(str,))


def test_same_local_names_keep_dependency_order_and_both_lifecycles() -> None:
    """实际准备、构造、激活和关闭都遵循两个独立模组的依赖。"""
    trace: list[tuple[str, str]] = []
    right_value = 7
    provider = "zzz_provider"
    consumer = "aaa_consumer"
    left = _spec(provider, str, "left-value", trace)
    right = _spec(consumer, int, right_value, trace, (str,))
    resolution = resolve((right, left))
    assert resolution.providers == {str: left.module_id, int: right.module_id}

    async def scenario() -> None:
        """用真实装配和生命周期执行核对登记权，不仅比较元数据。"""
        handle = await compose_managed(_Settings(), (right, left))
        stop = asyncio.Event()
        try:
            assert handle.assembly.get(str) == "left-value"
            assert handle.assembly.get(int) == right_value
            await handle.activate(stop)
        finally:
            await handle.close()

    asyncio.run(scenario())
    assert trace == [
        ("prepare", provider),
        ("prepare", consumer),
        ("build", provider),
        ("build", consumer),
        ("activate", provider),
        ("activate", consumer),
        ("close", consumer),
        ("close", provider),
    ]


def test_skipping_one_optional_namespace_does_not_remove_its_namesakes() -> None:
    """缺少依赖只跳过该完整身份，保留其他同名能力。"""
    trace: list[tuple[str, str]] = []
    retained = _spec("retained", str, "retained", trace)
    skipped = ModuleSpec(
        "shared", provides=(int,), requires=(float,), optional=True, manifest=ModuleManifest(namespace="skipped")
    )
    assembly = compose(_Settings(), (retained, skipped))
    assert assembly.get(str) == "retained"
    assert assembly.get_optional(int) is None
    assert assembly.modules == (retained,)


def test_priority_selection_does_not_execute_a_same_name_loser() -> None:
    """局部名称相同也不能绕过优先级，失选实现不参与构造。"""
    trace: list[tuple[str, str]] = []
    low = _spec("low", str, "low", trace)
    high = replace(_spec("high", str, "high", trace), priority=10)
    assert compose(_Settings(), (low, high)).get(str) == "high"
    assert trace == [("build", "high")]


def test_rollback_closes_all_constructed_namespaces_with_the_same_local_name() -> None:
    """后续构造失败后，回滚不能把两个已构造的同名模组合并成一个。"""
    trace: list[tuple[str, str]] = []
    left = _spec("left", str, "left", trace)
    right = _spec("right", int, 7, trace, (str,))

    @module(name="later", requires=(str, int))
    def later(context: ModuleContext) -> None:
        """两个依赖构造成功后制造明确失败。"""
        del context
        raise RuntimeError("后续构造失败")

    with pytest.raises(RuntimeError, match="后续构造失败"):
        asyncio.run(compose_managed(_Settings(), (left, right, later)))
    assert [namespace for phase, namespace in trace if phase == "close"] == ["right", "left"]


def test_duplicate_full_identity_is_rejected_even_with_different_release_versions() -> None:
    """同一环境不隐式选择同名发布版本，冲突必须在执行前明确失败。"""
    original = ModuleSpec("shared", provides=(str,), manifest=ModuleManifest("1", namespace="lab"))
    revised = replace(original, manifest=replace(original.manifest, version="2"))
    with pytest.raises(ValueError, match=r"名称重复.*lab:kernel/module/shared"):
        resolve((original, revised))
