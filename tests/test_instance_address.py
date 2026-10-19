"""实例地址保留 Bot 与原始运行身份，持久引用必须能严格还原。"""

import base64
import json

import pytest

from src.contracts.resource import ResourceInstance, ResourceKey, ResourceRef, resource_instance_identity
from src.contracts.resource_codec import parse_resource_instance, parse_resource_ref, resource_instance_data


@pytest.mark.parametrize("instance_id", ["run-1", "process:tree", "森林/树:一", " raw id ", "🌲"])
def test_instance_address_roundtrip_preserves_raw_identity(instance_id: str) -> None:
    """寻址不改写已有世界域和身份，也不依赖定义的可变别名。"""
    instance = ResourceInstance(
        instance_id, "lab:bot/forest", ResourceRef(ResourceKey.parse("lab:engine/process/tree"), "1")
    )
    key = ResourceKey.parse(str(instance.key))
    assert (key.namespace, key.domain, key.kind) == ("lab", "engine", "instance")
    assert resource_instance_identity(key) == (instance.bot_id, instance_id)
    assert parse_resource_instance(resource_instance_data(instance)) == instance
    assert ResourceInstance(instance_id, instance.bot_id, ResourceRef(instance.definition.key, "2")).key == key
    assert ResourceInstance(instance_id, "lab:bot/other", instance.definition).key != key


@pytest.mark.parametrize(
    "raw",
    [b'["aurora:bot/default", "run"]', b'["aurora:world/default","run"]', b'["aurora:bot/default",1]', b"{}", b"null"],
)
def test_instance_address_rejects_noncanonical_or_invalid_identity(raw: bytes) -> None:
    """同一身份只能有一种地址，错误类别和非文本身份不能被转换。"""
    path = "v1_" + base64.urlsafe_b64encode(raw).decode().rstrip("=")
    with pytest.raises(ValueError, match="地址无效"):
        resource_instance_identity(ResourceKey("aurora", "engine", "instance", path))


@pytest.mark.parametrize("path", ["v2_abc", "v1_", "v1_a", "v1____", "v1_e30"])
def test_instance_address_rejects_unknown_or_damaged_encoding(path: str) -> None:
    """无法准确恢复的地址不能退化成另一个原始 ID。"""
    with pytest.raises(ValueError, match="地址无效"):
        resource_instance_identity(ResourceKey("aurora", "engine", "instance", path))


@pytest.mark.parametrize(
    "data", [None, {}, {"key": 1, "revision": "1"}, {"key": "lab:engine/process/tree", "revision": 1}]
)
def test_persisted_resource_reference_rejects_missing_or_coerced_fields(data: object) -> None:
    """持久引用损坏时显式失败，不能猜测版本。"""
    with pytest.raises(ValueError):
        parse_resource_ref(data)


def test_instance_decoder_requires_complete_fixed_definition_and_text_identity() -> None:
    """只有可恢复到确定定义的实例事实才能进入资源目录。"""
    data = {
        "instance_id": "run",
        "bot_id": "aurora:bot/default",
        "definition": {"key": "lab:engine/process/tree", "revision": None},
    }
    with pytest.raises(ValueError, match="确定"):
        parse_resource_instance(data)
    data["instance_id"] = 1
    with pytest.raises(ValueError, match="文本"):
        parse_resource_instance(data)
    with pytest.raises(ValueError, match="必须包含"):
        parse_resource_instance(json.loads("{}"))
