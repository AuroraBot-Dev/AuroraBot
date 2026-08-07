"""让模型通过 aur.agent.delegate 创建子 Agent 的 Capability。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import (
    AgentDecision,
    DelegationRequest,
    ToolDefinition,
)

if TYPE_CHECKING:
    from src.contracts.agent import AgentContext
    from src.contracts.model import ToolCall

DELEGATE_TOOL = "aur.agent.delegate"

_DELEGATE_DESCRIPTION = "把一至四件彼此独立的工作托付给子 Agent；他们完成后会回来告诉我结果。"

_DELEGATE_SCHEMA: dict[str, object] = {
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
}


class DelegationCapability:
    """模型通过 aur.agent.delegate 创建子 Agent。"""

    @property
    def tool_names(self) -> frozenset[str]:
        """返回此 Capability 注册的工具名称集合。"""
        return frozenset({DELEGATE_TOOL})

    def tool_definitions(self, context: AgentContext) -> tuple[ToolDefinition, ...]:
        """仅在 profile 允许委派时提供委派工具定义。"""
        if not context.profile.can_delegate:
            return ()
        return (ToolDefinition(DELEGATE_TOOL, _DELEGATE_DESCRIPTION, _DELEGATE_SCHEMA),)

    def handle_tool(self, call: ToolCall) -> AgentDecision | None:
        """处理委派工具调用，验证任务参数并返回委派决策。"""
        if call.name != DELEGATE_TOOL:
            return None
        raw_tasks = call.arguments.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks or len(raw_tasks) > 4:  # noqa: PLR2004
            return AgentDecision(failure="delegate.tasks must contain one to four tasks")
        delegations: list[DelegationRequest] = []
        for raw in raw_tasks:
            if not isinstance(raw, dict) or not isinstance(raw.get("instruction"), str):
                return AgentDecision(failure="delegate task instruction is invalid")
            profile_id = raw.get("profile")
            if profile_id is not None and not isinstance(profile_id, str):
                return AgentDecision(failure="delegate task profile is invalid")
            delegations.append(DelegationRequest(raw["instruction"], profile_id))
        return AgentDecision(delegations=tuple(delegations))
