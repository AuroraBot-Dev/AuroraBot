"""模型工具定义使用可直接解析的原生资源身份。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.contracts.resource import ResourceKey

if TYPE_CHECKING:
    from src.contracts.tool import ToolDefinition

TOOL_MEDIA_TYPE = "application/vnd.aurora.tool+json;version=1"


def tool_resource_key(name: str) -> ResourceKey:
    """工具定义与工具标签属于不同类别，不能相互冒充。"""
    try:
        key = ResourceKey.parse(name)
        if key.domain == "tool" and key.kind == "definition":
            return key
    except ValueError as error:
        raise ValueError(f"工具身份必须形如 namespace:tool/definition/path：{name}") from error
    raise ValueError(f"工具身份必须形如 namespace:tool/definition/path：{name}")


def tool_content(definition: ToolDefinition) -> bytes:
    """规范正文覆盖模型可见接口，冻结映射转换为 JSON 对象并按键排序。"""
    return json.dumps(
        {
            "schema_version": 1,
            "name": definition.name,
            "description": definition.description,
            "parameters": definition.parameters,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=dict,
    ).encode("utf-8")
