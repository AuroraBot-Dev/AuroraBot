"""工具定义与集合标签有独立资源类别，原始服务器名称仍由适配器保留。"""

import pytest

from src.contracts import ToolDefinition
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
