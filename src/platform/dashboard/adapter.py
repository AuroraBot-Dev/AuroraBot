"""进程内 Dashboard Tool 执行适配器（RFC 0211：执行后提交 AMP 回执）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import (
    CapabilityDescriptor,
    ToolExecutionRequest,
    ToolExecutorBinding,
    tool_receipt_amp,
)

if TYPE_CHECKING:
    from src.contracts.ports import ExternalAmpIngressPort
    from src.platform.dashboard.service import ChatService

DASHBOARD_SEND_CAPABILITY = "aur.dashboard.send"
DASHBOARD_SEND_DESCRIPTOR = CapabilityDescriptor(
    id=DASHBOARD_SEND_CAPABILITY,
    description="通过已配置的 Dashboard 发送文本。",
    parameters_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 1},
            "complete_task": {
                "type": "boolean",
                "description": "发送后结束当前任务。",
                "default": False,
            },
        },
        "required": ["text"],
        "additionalProperties": False,
    },
    runtime_completion=True,
)


class DashboardPlatform:
    """执行 Dashboard 工具并提交 tool.{status} 回执 AMP（RFC 0211）。"""

    def __init__(self, chat: "ChatService", ingress: "ExternalAmpIngressPort") -> None:
        self._chat = chat
        self._ingress = ingress

    async def execute_tool(self, request: ToolExecutionRequest) -> None:
        """执行 Dashboard 消息发送工具，完成后提交回执 AMP。"""
        status, summary, result, error = await self._chat.execute_tool(request)
        await self._ingress.submit_amp(
            tool_receipt_amp(
                status=status,
                request=request,
                summary=summary,
                source_app="platform.dashboard",
                source_instance="local",
                result=result,
                error=error,
            )
        )

    @property
    def binding(self) -> ToolExecutorBinding:
        """返回此平台对应的工具绑定。"""
        return ToolExecutorBinding(DASHBOARD_SEND_DESCRIPTOR, self, "platform.dashboard", "local")
