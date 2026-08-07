"""让模型通过 aurora.agent.wait 等待子 Agent 的 Capability。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import (
    AgentDecision,
    ToolDefinition,
)

if TYPE_CHECKING:
    from src.contracts.agent import AgentContext
    from src.contracts.model import ToolCall

WAIT_TOOL = "aurora.agent.wait"

_WAIT_DESCRIPTION = "手头暂无其他事情时，安静等待仍在工作的子 Agent 回来。"

_WAIT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


class WaitCapability:
    """模型通过 aurora.agent.wait 等待仍在工作的子 Agent。"""

    @property
    def tool_names(self) -> frozenset[str]:
        """返回此 Capability 注册的工具名称集合。"""
        return frozenset({WAIT_TOOL})

    def tool_definitions(self, context: AgentContext) -> tuple[ToolDefinition, ...]:
        """仅在存在未终止子 Agent 时提供等待工具定义。"""
        if not any(not child.terminal for child in context.children):
            return ()
        return (ToolDefinition(WAIT_TOOL, _WAIT_DESCRIPTION, _WAIT_SCHEMA),)

    def handle_tool(self, call: ToolCall) -> AgentDecision | None:
        """处理等待工具调用，返回等待子 Agent 的决策。"""
        if call.name != WAIT_TOOL:
            return None
        return AgentDecision(wait_for_children=True)
