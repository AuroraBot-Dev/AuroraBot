"""In-process Dashboard Tool executor and recovery adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts.agent import CapabilityDescriptor
from src.localhost.ports import ToolExecutionRequest, ToolOutcome

if TYPE_CHECKING:
    from src.platform.dashboard.service import ChatService

DASHBOARD_SEND_CAPABILITY = "org.aurora.dashboard.send"
DASHBOARD_SEND_DESCRIPTOR = CapabilityDescriptor(
    id=DASHBOARD_SEND_CAPABILITY,
    description="Send text through the configured Dashboard.",
    parameters_schema={
        "type": "object",
        "properties": {"text": {"type": "string", "minLength": 1}},
        "required": ["text"],
        "additionalProperties": False,
    },
)


class DashboardPlatform:
    """Expose Dashboard-owned delivery and durable recovery to localhost."""

    def __init__(self, chat: ChatService) -> None:
        self._chat = chat

    async def execute_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        return await self._chat.execute_tool(request)

    async def recover_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        return await self._chat.recover_tool(request)
