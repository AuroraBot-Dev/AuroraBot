"""Capability that lets the model wait for child agents via aurora.agent.wait."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts.agent import AgentDecision
from src.contracts.model import ToolDefinition

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
        return frozenset({WAIT_TOOL})

    def tool_definitions(self, context: AgentContext) -> tuple[ToolDefinition, ...]:
        if not any(not child.terminal for child in context.children):
            return ()
        return (ToolDefinition(WAIT_TOOL, _WAIT_DESCRIPTION, _WAIT_SCHEMA),)

    def handle_tool(
        self,
        call: ToolCall,
        context: AgentContext,  # noqa: ARG002
        continuation: object = None,  # noqa: ARG002
        tools: tuple[object, ...] = (),  # noqa: ARG002
    ) -> AgentDecision | None:
        if call.name != WAIT_TOOL:
            return None
        return AgentDecision(wait_for_children=True)
