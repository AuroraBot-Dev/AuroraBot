"""外部工具辅助函数：complete_task 注入与 schema 检查。"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import TYPE_CHECKING

from src.contracts.model import ToolDefinition

if TYPE_CHECKING:
    from src.contracts.agent import CapabilityDescriptor

COMPLETE_TASK_DESCRIPTION = "完成后任务结束"


def capability_tool_definition(descriptor: CapabilityDescriptor) -> ToolDefinition:
    """从 CapabilityDescriptor 生成 ToolDefinition，必要时注入 complete_task 属性。"""
    schema = deepcopy(descriptor.parameters_schema)
    if not uses_runtime_complete_task(descriptor) or not _supports_root_property_injection(schema):
        return ToolDefinition(descriptor.id, descriptor.description, schema)
    raw_properties = schema.get("properties")
    properties = dict(raw_properties) if isinstance(raw_properties, dict) else {}
    schema["properties"] = properties
    properties["complete_task"] = {
        "type": "boolean",
        "description": COMPLETE_TASK_DESCRIPTION,
        "default": False,
    }
    return ToolDefinition(descriptor.id, descriptor.description, schema)


def uses_runtime_complete_task(descriptor: CapabilityDescriptor) -> bool:
    """检查 Capability 是否需要在运行时注入 complete_task 参数。"""
    return not _schema_defines_complete_task(descriptor.parameters_schema, descriptor.parameters_schema, set())


def _supports_root_property_injection(schema: dict[str, object]) -> bool:
    """检查 schema 根级别是否支持直接属性注入。"""
    return not any(keyword in schema for keyword in ("$ref", "allOf", "anyOf", "oneOf"))


def _schema_defines_complete_task(schema: object, root: dict[str, object], seen: set[int]) -> bool:  # noqa: C901
    """递归检查 schema 是否已定义 complete_task 属性。"""
    if not isinstance(schema, dict) or id(schema) in seen:
        return False
    seen.add(id(schema))
    properties = schema.get("properties")
    if isinstance(properties, dict) and "complete_task" in properties:
        return True
    patterns = schema.get("patternProperties")
    if isinstance(patterns, dict):
        for pattern in patterns:
            try:
                if re.search(str(pattern), "complete_task"):
                    return True
            except re.error:
                continue
    reference = schema.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/"):
        target: object = root
        for raw_part in reference[2:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                target = None
                break
            target = target[part]
        if _schema_defines_complete_task(target, root, seen):
            return True
    for keyword in ("allOf", "anyOf", "oneOf"):
        branches = schema.get(keyword)
        if isinstance(branches, list) and any(_schema_defines_complete_task(branch, root, seen) for branch in branches):
            return True
    return False
