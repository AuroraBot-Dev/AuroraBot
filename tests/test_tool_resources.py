"""工具定义与集合标签有独立资源类别，原始服务器名称仍由适配器保留。"""

import hashlib
import json
from dataclasses import replace

import pytest

from src.contracts import ChatMessage, ModelRequest, ToolDefinition
from src.contracts.resource import ResourceKey
from src.tools import is_tool_id


@pytest.mark.parametrize(
    "name",
    ["echo", "lab:tool/echo", "lab:tool/tag/echo", "lab:agent/definition/echo"],
)
def test_tool_definition_requires_its_own_complete_resource_identity(name: str) -> None:
    """标签不能作为模型工具，缺少类别的名称不能进入正式目录。"""
    assert not is_tool_id(name)
    with pytest.raises(ValueError, match="工具身份"):
        ToolDefinition(name, "核对结果", {"type": "object"})


def test_tool_definition_keeps_foreign_case_and_nested_raw_paths() -> None:
    """完整身份允许外部工具路径原样保留大小写与合法层级。"""
    definition = ToolDefinition("lab:tool/definition/Tools/Read", "读取记录", {"type": "object"})
    key = ResourceKey.parse(definition.name)
    assert (key.namespace, key.domain, key.kind, key.path) == ("lab", "tool", "definition", "Tools/Read")
    assert is_tool_id(definition.name)


def test_tool_version_covers_the_complete_frozen_interface() -> None:
    """接口字段改变即产生新版本，输入字典后续变化不能改写已采用的正文。"""
    modes = ["read", "check"]
    parameters = {"type": "object", "properties": {"mode": {"enum": modes}}}
    definition = ToolDefinition("lab:tool/definition/read", "读取记录", parameters)
    assert definition.ref.key == ResourceKey.parse(definition.name)
    assert definition.ref.revision == hashlib.sha256(definition.content).hexdigest()
    assert json.loads(definition.content)["parameters"] == parameters
    original = definition.content
    modes.append("overwrite")
    assert definition.content == original
    assert replace(definition, name="lab:tool/definition/check").ref != definition.ref
    assert replace(definition, description="另一份说明").ref != definition.ref
    assert replace(definition, parameters={"type": "object"}).ref != definition.ref


def test_equivalent_schema_key_order_does_not_change_tool_content_version() -> None:
    """字段声明顺序无关，数组顺序与约束内容仍保留在接口正文中。"""
    first = ToolDefinition("lab:tool/definition/read", "读取记录", {"type": "object", "required": ["mode"]})
    second = ToolDefinition("lab:tool/definition/read", "读取记录", {"required": ["mode"], "type": "object"})
    assert first.content == second.content
    assert first.ref == second.ref


def test_model_input_records_only_its_actual_tool_definitions_once() -> None:
    """请求自行绑定采用的接口，已有相同来源不重复，也不包含未采用接口。"""
    selected = ToolDefinition("lab:tool/definition/read", "读取记录", {"type": "object"})
    other = ToolDefinition("lab:tool/definition/write", "写入记录", {"type": "object"})
    request = ModelRequest(
        "test:ai/endpoint/model", (ChatMessage.system("主体身份"),), (selected,), resources=(selected.ref,)
    )
    assert request.resources == (selected.ref,)
    assert other.ref not in request.resources
