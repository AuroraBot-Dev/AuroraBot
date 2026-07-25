"""SpeechCapability — 决定 Agent 回复是否应朗读。

Agent 在决策空间内自主选择是否发起 TTS 朗读。
若启用，在 AgentDecision 中生成 tts.speak 工具请求。
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from src.contracts.agent import AgentDecision, ToolRequest
from src.contracts.model import ToolDefinition

if TYPE_CHECKING:
    from src.contracts.agent import AgentContext
    from src.contracts.model import ToolCall

SPEECH_TOOL = "tts.speak"

_SPEECH_DESCRIPTION = "将回复文本朗读出来。"

_SPEECH_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "需要朗读的文本内容。",
        }
    },
    "required": ["text"],
    "additionalProperties": False,
}


class _Msg(StrEnum):
    """SpeechCapability 内部错误消息。"""

    TTS_NOT_ENABLED = "tts.speak is not enabled"
    TEXT_REQUIRED = "tts.speak requires a non-empty text string"


class SpeechCapability:
    """决定 Agent 回复是否应朗读，生成 tts.speak 工具请求。"""

    def __init__(self) -> None:
        self._tts_enabled = False

    def install_tts_config(self, *, enabled: bool) -> None:
        """由进程组合根注入 TTS 配置。

        Args:
            enabled: 是否启用 TTS 朗读。
        """
        self._tts_enabled = enabled

    @property
    def tool_names(self) -> frozenset[str]:
        """此能力产生的 tool 名称集合。"""
        return frozenset({SPEECH_TOOL})

    def tool_definitions(self, context: AgentContext) -> tuple[ToolDefinition, ...]:  # noqa: ARG002
        """仅在 TTS 启用时提供朗读工具定义。"""
        if not self._tts_enabled:
            return ()
        return (ToolDefinition(SPEECH_TOOL, _SPEECH_DESCRIPTION, _SPEECH_SCHEMA),)

    def handle_tool(
        self,
        call: ToolCall,
        context: AgentContext,  # noqa: ARG002
        continuation: object = None,
        tools: tuple[object, ...] = (),  # noqa: ARG002
    ) -> AgentDecision | None:
        """处理 tts.speak 工具调用，验证参数并生成朗读工具请求。"""
        if call.name != SPEECH_TOOL:
            return None
        if not self._tts_enabled:
            return AgentDecision(failure=_Msg.TTS_NOT_ENABLED)
        text = call.arguments.get("text")
        if not isinstance(text, str) or not text.strip():
            return AgentDecision(failure=_Msg.TEXT_REQUIRED)
        continuation_dict: dict[str, object] | None = None
        if continuation is not None and callable(getattr(continuation, "to_dict", None)):
            continuation_dict = continuation.to_dict()  # type: ignore[union-attr]
        return AgentDecision(
            tool_request=ToolRequest(
                capability=SPEECH_TOOL,
                parameters={"text": text},
                tool_call_id=call.call_id,
                continuation=continuation_dict,
            )
        )
