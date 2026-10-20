"""验证统一寻址维度、版本绑定和不可变传输数据。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aurorabot.contracts.data import freeze_object
from aurorabot.contracts.resource import ResourceAlias, ResourceDescriptor, ResourceInstance, ResourceKey, ResourceRef

if TYPE_CHECKING:
    from typing import Any


def test_resource_key_keeps_namespace_domain_kind_and_nested_path_separate() -> None:
    """解析和显示共享一种规范，路径可以包含子目录。"""
    key = ResourceKey.parse("lab:memory/model/temporal/encoder")
    assert (key.namespace, key.domain, key.kind, key.path) == ("lab", "memory", "model", "temporal/encoder")
    assert str(key) == "lab:memory/model/temporal/encoder"


@pytest.mark.parametrize("text", ["lab:memory", "lab:memory/model", "lab:memory/model/", "lab:memory/Model/tgn"])
def test_resource_key_rejects_ambiguous_or_invalid_dimensions(text: str) -> None:
    """缺失领域维度或非法类别不能进入注册表。"""
    with pytest.raises(ValueError):
        ResourceKey.parse(text)


def test_resource_versions_aliases_and_running_instances_have_distinct_identity() -> None:
    """切换别名不会改写已有运行引用的定义版本。"""
    model = ResourceKey.parse("lab:rhythm/model/gru")
    first = ResourceRef(model, "weights-a")
    second = ResourceRef(model, "weights-b")
    default = ResourceKey.parse("aurora:rhythm/model/default")
    alias = ResourceAlias(default, second)
    instance = ResourceInstance("run-1", "aurora:bot/default", first)
    assert alias.target != instance.definition
    assert instance.definition.revision == "weights-a"


def test_protocol_payloads_cannot_be_mutated_through_nested_containers() -> None:
    """原始数据的后续变化不能越过协议边界。"""
    data: dict[str, Any] = {"options": [{"enabled": True}]}
    descriptor = ResourceDescriptor(
        ResourceRef(ResourceKey.parse("lab:memory/model/tgn"), "1"), "时序图模型", metadata=data
    )
    data["options"][0]["enabled"] = False
    assert descriptor.metadata["options"][0]["enabled"] is True
    with pytest.raises(TypeError):
        descriptor.metadata["options"][0]["enabled"] = False


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object(), {1: "invalid"}])
def test_protocol_payloads_reject_nonportable_values(value: object) -> None:
    """不能稳定序列化的内容在声明处失败。"""
    with pytest.raises((TypeError, ValueError)):
        freeze_object({"value": value})


def test_definitions_and_instances_require_concrete_versions() -> None:
    """可变别名只参与解析，持久定义与实例必须冻结版本。"""
    key = ResourceKey.parse("lab:memory/model/tgn")
    with pytest.raises(ValueError, match="确定版本"):
        ResourceDescriptor(ResourceRef(key), "时序图模型")
    with pytest.raises(ValueError, match="确定"):
        ResourceInstance("run", "aurora:bot/default", ResourceRef(key))
    with pytest.raises(ValueError, match="领域和类别"):
        ResourceAlias(ResourceKey.parse("lab:memory/query/recall"), ResourceRef(key, "1"))
