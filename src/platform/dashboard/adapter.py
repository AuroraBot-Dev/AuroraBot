"""进程内 Dashboard Tool 执行与恢复适配器。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts.agent import CapabilityDescriptor
from src.localhost.ports import ToolExecutionRequest, ToolOutcome

if TYPE_CHECKING:
    from src.platform.dashboard.service import ChatService

DASHBOARD_SEND_CAPABILITY = "org.aurora.dashboard.send"
DASHBOARD_SEND_DESCRIPTOR = CapabilityDescriptor(
    id=DASHBOARD_SEND_CAPABILITY,
    description="通过已配置的 Dashboard 发送文本。",
    parameters_schema={
        "type": "object",
        "properties": {"text": {"type": "string", "minLength": 1}},
        "required": ["text"],
        "additionalProperties": False,
    },
)


class DashboardPlatform:
    """将 Dashboard 的消息投递和持久化恢复能力暴露给 localhost。"""

    def __init__(self, chat: ChatService) -> None:
        """绑定 ChatService 作为 Tool 执行的委托目标。

        Args:
            chat: Dashboard 聊天服务实例。
        """
        self._chat = chat

    async def execute_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        """执行 Dashboard 消息发送 Tool，委托给 ChatService。"""
        return await self._chat.execute_tool(request)

    async def recover_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        """恢复 Dashboard Tool 执行状态，委托给 ChatService。"""
        return await self._chat.recover_tool(request)
