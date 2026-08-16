"""SpeechCapability — 未启用的朗读决策壳。

当前没有 TTS 配置与执行器绑定，因此从不暴露 ``aur.agent.speech``
工具定义；任何意外调用都确定性返回失败，避免生成悬空工具请求。
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from src.contracts import (
    AgentDecision,
    ToolDefinition,
)

if TYPE_CHECKING:
    from src.contracts.agent import AgentContext
    from src.contracts.model import ToolCall

SPEECH_TOOL = "aur.agent.speech"


class _Msg(StrEnum):
    """SpeechCapability 内部错误消息。"""

    TTS_NOT_ENABLED = "aur.agent.speech is not enabled"


class SpeechCapability:
    """未启用的朗读决策壳：不暴露工具定义，调用即确定性失败。"""

    @property
    def tool_names(self) -> frozenset[str]:
        """此能力产生的 tool 名称集合。"""
        return frozenset({SPEECH_TOOL})

    def tool_definitions(self, context: AgentContext) -> tuple[ToolDefinition, ...]:  # noqa: ARG002
        """TTS 未启用，不向模型暴露朗读工具定义。"""
        return ()

    def handle_tool(self, call: ToolCall) -> AgentDecision | None:
        """拒绝未启用的朗读工具调用。"""
        if call.name != SPEECH_TOOL:
            return None
        return AgentDecision(failure=_Msg.TTS_NOT_ENABLED)
