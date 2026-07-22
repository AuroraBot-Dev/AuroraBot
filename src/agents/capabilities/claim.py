"""Capability that lets the model claim ambient situations via aurora.situation.claim."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts.agent import AgentDecision
from src.contracts.model import (
    ModelContinuation,
    ModelRequest,
    ToolDefinition,
    append_tool_result,
)

if TYPE_CHECKING:
    from src.contracts.agent import AgentContext
    from src.contracts.model import ToolCall

CLAIM_TOOL = "aurora.situation.claim"

_CLAIM_DESCRIPTION = "认领我愿意接住的未分配情境。"

_CLAIM_SCHEMA: dict[str, object] = {
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
}


class ClaimCapability:
    """模型通过 aurora.situation.claim 认领未分配的情景事件。"""

    def __init__(self, *, composer: object = None) -> None:
        self._composer = composer

    def install_prompt_composer(self, composer: object) -> None:
        self._composer = composer

    @property
    def tool_names(self) -> frozenset[str]:
        return frozenset({CLAIM_TOOL})

    def tool_definitions(self, context: AgentContext) -> tuple[ToolDefinition, ...]:
        if not context.brain.ambient_situations:
            return ()
        return (ToolDefinition(CLAIM_TOOL, _CLAIM_DESCRIPTION, _CLAIM_SCHEMA),)

    def handle_tool(
        self,
        call: ToolCall,
        context: AgentContext,
        continuation: object = None,
        tools: tuple[object, ...] = (),
    ) -> AgentDecision | None:
        if call.name != CLAIM_TOOL:
            return None
        raw_ids = call.arguments.get("situation_ids")
        if not isinstance(raw_ids, list) or not all(isinstance(item, str) for item in raw_ids):
            return AgentDecision(failure="situation_ids must contain strings")
        if not isinstance(continuation, ModelContinuation):
            return AgentDecision(failure="situation claim requires model continuation")
        continuation = append_tool_result(
            continuation,
            call.call_id,
            {"claimed": raw_ids},
            is_error=False,
        )
        request = self._continuation_request(context, continuation, tools)
        return AgentDecision(model_request=request.to_dict(), claims=tuple(raw_ids))

    def _continuation_request(
        self, context: AgentContext, continuation: ModelContinuation, tools: tuple[object, ...]
    ) -> ModelRequest:
        return ModelRequest(
            role=context.profile.model_role,
            messages=(),
            required_capabilities=frozenset({"chat", "tools"}),
            response_mode="native" if context.profile.model_role == "agent" else "normalized",
            tools=tuple(t for t in tools if isinstance(t, ToolDefinition)),
            continuation=continuation,
            parallel_tool_calls=False,
            cancel_policy="on_external_activity" if context.task.autonomous else "never",
        )
