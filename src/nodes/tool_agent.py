"""Shared RFC 0008 serial tool-agent node behavior."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.ai.contracts import ModelContinuation, ModelMessage, ModelRequest, ModelResult, ToolDefinition
from src.ai.vnext import append_tool_result
from src.utils.log_utils import get_logger

logger = get_logger("aurora.node.tool_agent")

if TYPE_CHECKING:
    from src.kernel.node import NodeContext

_ESCALATE_TOOL = "aurora.cognition.escalate"
_REPLY_CAPABILITIES = {
    "org.aurora.console.send_message",
    "org.aurora.dashboard.send_message",
}


@dataclass(frozen=True, slots=True)
class ToolAgentPolicy:
    role: str
    native: bool
    may_escalate: bool


class SerialToolAgentNode:
    def __init__(self, policy: ToolAgentPolicy) -> None:
        self.policy = policy

    async def execute(self, context: NodeContext) -> None:
        event_type = context.amp.payload.type
        logger.debug(
            "cognitive node entered record_id=%s episode_id=%s node_id=%s model_role=%s event_type=%s round=%s",
            context.record.record_id,
            context.record.episode_id,
            context.node_id,
            self.policy.role,
            event_type,
            context.episode_snapshot.get("round"),
        )
        if event_type == "model.completed":
            self._handle_model_result(context)
            return
        if event_type == "model.failed":
            logger.warning(
                "model failure received record_id=%s episode_id=%s node_id=%s model_role=%s",
                context.record.record_id,
                context.record.episode_id,
                context.node_id,
                self.policy.role,
            )
            context.finish_episode("error", str(context.amp.payload.data.get("error", "model_failed")))
            return
        if event_type in {"effect.succeeded", "effect.failed"}:
            self._resume_after_effect(context)
            return
        self._request_initial_model(context)

    def _request_initial_model(self, context: NodeContext) -> None:
        episode = context.episode_snapshot
        prompt = {
            "event": context.amp.to_dict(),
            "episode": {
                "id": episode.get("episode_id"),
                "autonomous": episode.get("autonomous", False),
                "round": episode.get("round", 0),
                "model_calls": episode.get("model_calls", 0),
                "tool_calls": episode.get("tool_calls", 0),
            },
            "instruction": (
                "Use an available tool for every external action or publication. "
                "Plain text is internal thought and will not be published. "
                "Return no tool call when silence is the correct outcome."
            ),
        }
        if self.policy.may_escalate:
            prompt["instruction"] += " Use aurora.cognition.escalate only when the native agent is necessary."
        tools = self._tools(context)
        logger.debug(
            "initial model request prepared record_id=%s episode_id=%s node_id=%s model_role=%s tools=%d autonomous=%s",
            context.record.record_id,
            context.record.episode_id,
            context.node_id,
            self.policy.role,
            len(tools),
            episode.get("autonomous", False),
        )
        context.defer_model(
            ModelRequest(
                role=self.policy.role,
                messages=(
                    ModelMessage("system", context.soul_content),
                    ModelMessage("user", json.dumps(prompt, ensure_ascii=False)),
                ),
                required_capabilities=frozenset({"chat", "tools"}),
                response_mode="native" if self.policy.native else "normalized",
                tools=tools,
                parallel_tool_calls=False,
                cancel_policy=(
                    "on_external_activity" if context.episode_snapshot.get("autonomous") is True else "never"
                ),
            )
        )

    def _handle_model_result(self, context: NodeContext) -> None:
        result = ModelResult.from_dict(context.amp.payload.data)
        if len(result.tool_calls) > 1:
            logger.error(
                "parallel tool calls rejected record_id=%s episode_id=%s node_id=%s count=%d",
                context.record.record_id,
                context.record.episode_id,
                context.node_id,
                len(result.tool_calls),
            )
            context.finish_episode("error", "parallel_tool_calls_rejected")
            return
        if not result.tool_calls:
            logger.debug(
                "model selected silence record_id=%s episode_id=%s node_id=%s finish_reason=%s unpublished_text=%s",
                context.record.record_id,
                context.record.episode_id,
                context.node_id,
                result.finish_reason,
                bool(result.text),
            )
            context.finish_episode("silent", "unpublished_text" if result.text else "no_action")
            return
        call = result.tool_calls[0]
        if call.name == _ESCALATE_TOOL:
            if not self.policy.may_escalate:
                logger.error(
                    "unexpected escalation rejected record_id=%s episode_id=%s node_id=%s call_id=%s",
                    context.record.record_id,
                    context.record.episode_id,
                    context.node_id,
                    call.call_id,
                )
                context.finish_episode("error", "unexpected_escalation")
                return
            reason = call.arguments.get("reason", "fast gate requested native agent")
            logger.info(
                "cognition escalated record_id=%s episode_id=%s node_id=%s call_id=%s",
                context.record.record_id,
                context.record.episode_id,
                context.node_id,
                call.call_id,
            )
            context.publish_event(
                "cognition.escalated",
                {"reason": str(reason)},
                "Fast gate escalated the episode",
            )
            return
        logger.debug(
            "tool call selected record_id=%s episode_id=%s node_id=%s call_id=%s capability=%s argument_keys=%s",
            context.record.record_id,
            context.record.episode_id,
            context.node_id,
            call.call_id,
            call.name,
            sorted(call.arguments),
        )
        context.request_effect(
            call.name,
            call.arguments,
            f"Model requested {call.name}",
            tool_call_id=call.call_id,
            continuation=result.continuation,
        )

    def _resume_after_effect(self, context: NodeContext) -> None:
        request_data = self._latest_effect_request(context)
        continuation_raw = request_data.get("model_continuation")
        call_id = request_data.get("tool_call_id")
        if not isinstance(continuation_raw, dict) or not isinstance(call_id, str):
            logger.error(
                "effect continuation missing record_id=%s episode_id=%s node_id=%s event_type=%s",
                context.record.record_id,
                context.record.episode_id,
                context.node_id,
                context.amp.payload.type,
            )
            context.finish_episode("error", "effect_receipt_missing_model_continuation")
            return
        continuation = ModelContinuation.from_dict(continuation_raw)
        receipt = context.amp.payload.data
        is_error = context.amp.payload.type == "effect.failed"
        output = receipt.get("error") if is_error else receipt.get("result", {})
        continuation = append_tool_result(continuation, call_id, output, is_error=is_error)
        logger.debug(
            "effect receipt resumes model record_id=%s episode_id=%s node_id=%s call_id=%s failed=%s",
            context.record.record_id,
            context.record.episode_id,
            context.node_id,
            call_id,
            is_error,
        )
        context.defer_model(
            ModelRequest(
                role=self.policy.role,
                messages=(),
                required_capabilities=frozenset({"chat", "tools"}),
                response_mode="native" if self.policy.native else "normalized",
                tools=self._tools(context),
                continuation=continuation,
                parallel_tool_calls=False,
                cancel_policy=(
                    "on_external_activity" if context.episode_snapshot.get("autonomous") is True else "never"
                ),
            )
        )

    @staticmethod
    def _latest_effect_request(context: NodeContext) -> dict[str, Any]:
        transcript = context.episode_snapshot.get("transcript", [])
        if not isinstance(transcript, list):
            return {}
        for item in reversed(transcript):
            if not isinstance(item, dict) or item.get("kind") != "effect.requested":
                continue
            amp = item.get("amp")
            if isinstance(amp, dict):
                payload = amp.get("payload")
                if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
                    return dict(payload["data"])
        return {}

    def _tools(self, context: NodeContext) -> tuple[ToolDefinition, ...]:
        descriptors = context.configuration_snapshot.get("capability_descriptors", [])
        reply_capability = self._reply_capability(context)
        tools = [
            ToolDefinition(
                str(item["id"]),
                str(item.get("description", "")),
                dict(item["parameters_schema"]),
            )
            for item in descriptors
            if isinstance(item, dict)
            and (str(item.get("id")) not in _REPLY_CAPABILITIES or str(item.get("id")) == reply_capability)
        ]
        if self.policy.may_escalate:
            tools.append(
                ToolDefinition(
                    _ESCALATE_TOOL,
                    "Escalate this episode to the native quality agent.",
                    {
                        "type": "object",
                        "properties": {"reason": {"type": "string"}},
                        "required": ["reason"],
                        "additionalProperties": False,
                    },
                )
            )
        return tuple(tools)

    @staticmethod
    def _reply_capability(context: NodeContext) -> str:
        transcript = context.episode_snapshot.get("transcript", [])
        if isinstance(transcript, list):
            for item in transcript:
                if not isinstance(item, dict) or item.get("kind") != "event":
                    continue
                amp = item.get("amp")
                if not isinstance(amp, dict):
                    continue
                payload = amp.get("payload")
                if not isinstance(payload, dict):
                    continue
                data = payload.get("data")
                if isinstance(data, dict) and data.get("reply_capability") in _REPLY_CAPABILITIES:
                    return str(data["reply_capability"])
        return "org.aurora.console.send_message"
