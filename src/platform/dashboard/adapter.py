"""In-process Dashboard Publication executor and recovery adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts.agent import CapabilityDescriptor
from src.localhost.ports import PublicationExecutionRequest, PublicationOutcome

if TYPE_CHECKING:
    from src.platform.dashboard.service import ChatService

DASHBOARD_ENDPOINT = "dashboard.local"
DASHBOARD_AUDIENCE = "owner.local"
DASHBOARD_REPLY_CAPABILITY = "org.aurora.dashboard.send_message"
DASHBOARD_REPLY_DESCRIPTOR = CapabilityDescriptor(
    id=DASHBOARD_REPLY_CAPABILITY,
    description="Reply to the owner through the local Dashboard.",
    parameters_schema={
        "type": "object",
        "properties": {"text": {"type": "string", "minLength": 1}},
        "required": ["text"],
        "additionalProperties": False,
    },
    kind="publication",
    endpoint=DASHBOARD_ENDPOINT,
    operation="reply",
    root_only=True,
)


class DashboardPlatform:
    """Expose Dashboard-owned delivery and durable recovery to localhost."""

    def __init__(self, chat: ChatService) -> None:
        self._chat = chat

    async def execute_publication(self, request: PublicationExecutionRequest) -> PublicationOutcome:
        return await self._chat.execute_publication(request)

    async def recover_publication(self, request: PublicationExecutionRequest) -> PublicationOutcome:
        return await self._chat.recover_publication(request)
