"""Build Agent-owned Tool definitions while preserving external Tool contracts."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import TYPE_CHECKING

from src.contracts.model import ToolDefinition

if TYPE_CHECKING:
    from src.contracts.agent import AgentContext, CapabilityDescriptor

DELEGATE_TOOL = "aurora.agent.delegate"
WAIT_TOOL = "aurora.agent.wait"
CLAIM_TOOL = "aurora.situation.claim"
MEMORY_QUERY_TOOL = "aurora.memory.query"

_INTERNAL_TOOL_DESCRIPTIONS = {
    DELEGATE_TOOL: "把一至四件彼此独立的工作托付给子 Agent；他们完成后会回来告诉我结果。",
    WAIT_TOOL: "手头暂无其他事情时，安静等待仍在工作的子 Agent 回来。",
    CLAIM_TOOL: "认领我愿意接住的未分配情境。",
    MEMORY_QUERY_TOOL: "向记忆 Agent 询问过去留下的线索；没有配置记忆 Agent 时会平静地返回不可用。",
}
COMPLETE_TASK_DESCRIPTION = "这次投递成功后，为我当前这段工作画上句点。"
_DUPLICATE_TOOL_IDS = "model Tool IDs must be unique"


def build_tool_definitions(context: AgentContext) -> tuple[ToolDefinition, ...]:
    tools = [capability_tool_definition(item) for item in context.capabilities]
    if context.profile.can_delegate:
        tools.append(
            ToolDefinition(
                DELEGATE_TOOL,
                _INTERNAL_TOOL_DESCRIPTIONS[DELEGATE_TOOL],
                {
                    "type": "object",
                    "properties": {
                        "tasks": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "instruction": {
                                        "type": "string",
                                        "description": "交给子 Agent 的一件清晰、完整、可以独立完成的事。",
                                    },
                                    "profile": {
                                        "type": "string",
                                        "description": "需要指定时，选择一个获准的 Agent profile。",
                                    },
                                },
                                "required": ["instruction"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["tasks"],
                    "additionalProperties": False,
                },
            )
        )
    if any(not child.terminal for child in context.children):
        tools.append(
            ToolDefinition(
                WAIT_TOOL,
                _INTERNAL_TOOL_DESCRIPTIONS[WAIT_TOOL],
                {"type": "object", "properties": {}, "additionalProperties": False},
            )
        )
    if context.brain.ambient_situations:
        tools.append(
            ToolDefinition(
                CLAIM_TOOL,
                _INTERNAL_TOOL_DESCRIPTIONS[CLAIM_TOOL],
                {
                    "type": "object",
                    "properties": {
                        "situation_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "description": "我愿意负责的情境 ID。",
                        }
                    },
                    "required": ["situation_ids"],
                    "additionalProperties": False,
                },
            )
        )
    tools.append(
        ToolDefinition(
            MEMORY_QUERY_TOOL,
            _INTERNAL_TOOL_DESCRIPTIONS[MEMORY_QUERY_TOOL],
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "我想从过往寻找什么。"},
                    "scope": {"type": "string", "default": "global", "description": "寻找记忆的范围。"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 32,
                        "default": 8,
                        "description": "最多带回多少条线索。",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        )
    )
    names = [tool.name for tool in tools]
    if len(names) != len(set(names)):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        message = f"{_DUPLICATE_TOOL_IDS}: {duplicates}"
        raise ValueError(message)
    return tuple(tools)


def uses_runtime_complete_task(descriptor: CapabilityDescriptor) -> bool:
    return not _schema_defines_complete_task(descriptor.parameters_schema, descriptor.parameters_schema, set())


def capability_tool_definition(descriptor: CapabilityDescriptor) -> ToolDefinition:
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


def _supports_root_property_injection(schema: dict[str, object]) -> bool:
    return not any(keyword in schema for keyword in ("$ref", "allOf", "anyOf", "oneOf"))


def _schema_defines_complete_task(  # noqa: C901 - JSON Schema composition has several independent branches
    schema: object, root: dict[str, object], seen: set[int]
) -> bool:
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
