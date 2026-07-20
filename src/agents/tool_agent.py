"""One serial tool-capable handler shared by every RFC 0012 Agent profile."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from src.contracts.agent import (
    AgentContext,
    AgentDecision,
    CapabilityDescriptor,
    Completion,
    DelegationRequest,
    EffectRequest,
    PublicationRequest,
)
from src.contracts.memory import MemoryFailure, MemoryQuery
from src.contracts.model import (
    ModelContinuation,
    ModelMessage,
    ModelRequest,
    ModelResult,
    ToolDefinition,
    append_tool_result,
)
from src.utils.log_utils import get_logger

logger = get_logger("aurora.agent.tool")

DELEGATE_TOOL = "aurora.agent.delegate"
WAIT_TOOL = "aurora.agent.wait"
CLAIM_TOOL = "aurora.situation.claim"
MEMORY_QUERY_TOOL = "aurora.memory.query"


class ToolAgent:
    """A deterministic state-machine adapter around provider-native Tool IR."""

    def handle(self, context: AgentContext) -> AgentDecision:
        message_type = context.message.type
        logger.debug(
            "Agent turn entered task_id=%s agent_id=%s profile=%s message_type=%s depth=%d",
            context.task.task_id,
            context.agent.agent_id,
            context.profile.id,
            message_type,
            context.agent.depth,
        )
        if message_type == "model.completed":
            return self._handle_model_result(context)
        if message_type == "model.failed":
            error = str(context.message.payload.get("error", "model_failed"))
            reply = self._safe_reply(context, "抱歉，我暂时无法完成这次回复。请稍后重试。")
            if reply is not None:
                logger.warning(
                    "Root model failed; publishing safe fallback task_id=%s agent_id=%s",
                    context.task.task_id,
                    context.agent.agent_id,
                )
                return AgentDecision(publication_request=reply)
            return AgentDecision(failure=error)
        if message_type in {"effect.succeeded", "effect.failed"}:
            return self._resume_effect(context)
        if message_type in {
            "publication.succeeded",
            "publication.failed",
            "publication.delivery_unknown",
        }:
            return self._resume_publication(context)
        return self._request_model(context)

    def _request_model(self, context: AgentContext) -> AgentDecision:
        prompt = {
            "profile_instruction": context.profile.prompt,
            "task": context.task.to_dict(),
            "agent": {
                "agent_id": context.agent.agent_id,
                "parent_agent_id": context.agent.parent_agent_id,
                "assignment": context.agent.assignment,
                "depth": context.agent.depth,
            },
            "message": context.message.to_dict(),
            "children": [child.to_dict() for child in context.children],
            "brain_context": context.brain.to_dict(),
            "rules": [
                "Use tools for external actions. A final plain-text answer is published "
                "through the current reply channel.",
                "Delegate only independent, bounded work that materially helps this task.",
                "A child result is evidence for you to continue working, not the final user response.",
                "Only the root Agent can publish. Set complete_task=false when more work or another reply follows.",
            ],
        }
        state_patch = self._initial_reply_route_patch(context)
        request = ModelRequest(
            role=context.profile.model_role,
            messages=(
                ModelMessage("system", context.brain.persona["content"]),
                ModelMessage("user", json.dumps(prompt, ensure_ascii=False)),
            ),
            required_capabilities=frozenset({"chat", "tools"}),
            response_mode="native" if context.profile.model_role == "agent" else "normalized",
            tools=self._tools(context),
            parallel_tool_calls=False,
            cancel_policy="on_external_activity" if context.task.autonomous else "never",
        )
        return AgentDecision(model_request=request.to_dict(), state_patch=state_patch)

    def _handle_model_result(self, context: AgentContext) -> AgentDecision:
        result = ModelResult.from_dict(context.message.payload)
        if len(result.tool_calls) > 1:
            return AgentDecision(failure="parallel_tool_calls_rejected")
        if not result.tool_calls:
            text = result.text.strip()
            if context.agent.parent_agent_id is not None:
                return AgentDecision(completion=Completion(text or "Subtask completed without a textual result"))
            reply = self._safe_reply(context, text) if text else None
            if reply is not None:
                return AgentDecision(publication_request=reply)
            return AgentDecision(completion=Completion("unpublished_text" if text else "no_action", silent=True))
        call = result.tool_calls[0]
        if call.name == DELEGATE_TOOL:
            raw_tasks = call.arguments.get("tasks")
            if not isinstance(raw_tasks, list) or not raw_tasks or len(raw_tasks) > 4:
                return AgentDecision(failure="delegate.tasks must contain one to four tasks")
            delegations: list[DelegationRequest] = []
            for raw in raw_tasks:
                if not isinstance(raw, dict) or not isinstance(raw.get("instruction"), str):
                    return AgentDecision(failure="delegate task instruction is invalid")
                profile_id = raw.get("profile")
                if profile_id is not None and not isinstance(profile_id, str):
                    return AgentDecision(failure="delegate task profile is invalid")
                delegations.append(DelegationRequest(raw["instruction"], profile_id))
            return AgentDecision(delegations=tuple(delegations))
        if call.name == WAIT_TOOL:
            return AgentDecision(wait_for_children=True)
        if call.name == CLAIM_TOOL:
            return self._handle_situation_claim(context, result)
        if call.name == MEMORY_QUERY_TOOL:
            return self._handle_memory_query(context, result)
        return self._capability_decision(context, result)

    def _capability_decision(self, context: AgentContext, result: ModelResult) -> AgentDecision:
        call = result.tool_calls[0]
        descriptor = next((item for item in context.capabilities if item.id == call.name), None)
        if descriptor is not None and descriptor.kind == "publication":
            return self._publication_decision(context, result, descriptor)
        return AgentDecision(
            effect_request=EffectRequest(
                capability=call.name,
                parameters=call.arguments,
                tool_call_id=call.call_id,
                continuation=result.continuation.to_dict() if result.continuation is not None else None,
            )
        )

    def _handle_situation_claim(self, context: AgentContext, result: ModelResult) -> AgentDecision:
        call = result.tool_calls[0]
        raw_ids = call.arguments.get("situation_ids")
        if not isinstance(raw_ids, list) or not all(isinstance(item, str) for item in raw_ids):
            return AgentDecision(failure="situation_ids must contain strings")
        continuation = result.continuation
        if continuation is None:
            return AgentDecision(failure="situation claim requires model continuation")
        continuation = append_tool_result(
            continuation,
            call.call_id,
            {"claimed": raw_ids},
            is_error=False,
        )
        request = self._continuation_request(context, continuation)
        return AgentDecision(model_request=request.to_dict(), claims=tuple(raw_ids))

    def _handle_memory_query(self, context: AgentContext, result: ModelResult) -> AgentDecision:
        call = result.tool_calls[0]
        query = call.arguments.get("query")
        scope = call.arguments.get("scope", "global")
        limit = call.arguments.get("limit", 8)
        valid_limit = isinstance(limit, int) and not isinstance(limit, bool) and 1 <= limit <= 32
        if not isinstance(query, str) or not isinstance(scope, str) or not valid_limit:
            return AgentDecision(failure="memory query is invalid")
        memory_query = MemoryQuery(query, scope, limit)
        if context.memory_agent_profile is not None:
            return AgentDecision(
                delegations=(
                    DelegationRequest(
                        json.dumps({"type": "memory.query", **memory_query.to_dict()}, ensure_ascii=False),
                        context.memory_agent_profile,
                    ),
                )
            )
        continuation = result.continuation
        if continuation is None:
            return AgentDecision(failure="memory query requires model continuation")
        continuation = append_tool_result(
            continuation,
            call.call_id,
            {"ok": False, **MemoryFailure().to_dict()},
            is_error=False,
        )
        request = self._continuation_request(context, continuation)
        return AgentDecision(model_request=request.to_dict())

    def _resume_effect(self, context: AgentContext) -> AgentDecision:
        request = context.message.payload.get("request")
        if not isinstance(request, dict):
            return AgentDecision(failure="effect receipt lacks original request")
        raw_continuation = request.get("continuation")
        call_id = request.get("tool_call_id")
        if not isinstance(raw_continuation, dict) or not isinstance(call_id, str):
            return AgentDecision(failure="effect receipt lacks model continuation")
        continuation = ModelContinuation.from_dict(raw_continuation)
        failed = context.message.type == "effect.failed"
        output = context.message.payload.get("error") if failed else context.message.payload.get("result", {})
        continuation = append_tool_result(continuation, call_id, output, is_error=failed)
        model_request = self._continuation_request(context, continuation)
        return AgentDecision(model_request=model_request.to_dict())

    def _resume_publication(self, context: AgentContext) -> AgentDecision:
        request = context.message.payload.get("request")
        if not isinstance(request, dict):
            return AgentDecision(failure="Publication receipt lacks original request")
        raw_continuation = request.get("continuation")
        call_id = request.get("tool_call_id")
        if not isinstance(raw_continuation, dict) or not isinstance(call_id, str):
            return self._request_model(context)
        continuation = ModelContinuation.from_dict(raw_continuation)
        status = {
            "publication.succeeded": "accepted",
            "publication.failed": "failed",
            "publication.delivery_unknown": "delivery_unknown",
        }[context.message.type]
        output: dict[str, object] = {"status": status}
        if status == "accepted":
            output["result"] = context.message.payload.get("result", {})
        else:
            output["error"] = context.message.payload.get("error", status)
        continuation = append_tool_result(continuation, call_id, output, is_error=status != "accepted")
        return AgentDecision(model_request=self._continuation_request(context, continuation).to_dict())

    def _continuation_request(self, context: AgentContext, continuation: ModelContinuation) -> ModelRequest:
        return ModelRequest(
            role=context.profile.model_role,
            messages=(),
            required_capabilities=frozenset({"chat", "tools"}),
            response_mode="native" if context.profile.model_role == "agent" else "normalized",
            tools=self._tools(context),
            continuation=continuation,
            parallel_tool_calls=False,
            cancel_policy="on_external_activity" if context.task.autonomous else "never",
        )

    def _tools(self, context: AgentContext) -> tuple[ToolDefinition, ...]:
        tools = [self._capability_tool(item) for item in context.capabilities]
        if context.profile.can_delegate:
            tools.append(
                ToolDefinition(
                    DELEGATE_TOOL,
                    "Create one to four bounded child Agents that report each result back to you.",
                    {
                        "type": "object",
                        "properties": {
                            "tasks": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 4,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "instruction": {"type": "string"},
                                        "profile": {"type": "string"},
                                    },
                                    "required": ["instruction"],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["tasks"],
                        "additionalProperties": False,
                    },
                )
            )
        if any(not child.terminal for child in context.children):
            tools.append(
                ToolDefinition(
                    WAIT_TOOL,
                    "Wait for remaining active child Agents without performing another action.",
                    {"type": "object", "properties": {}, "additionalProperties": False},
                )
            )
        if context.brain.ambient_situations:
            tools.append(
                ToolDefinition(
                    CLAIM_TOOL,
                    "Claim unassigned situations that this Agent will handle.",
                    {
                        "type": "object",
                        "properties": {"situation_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
                        "required": ["situation_ids"],
                        "additionalProperties": False,
                    },
                )
            )
        tools.append(
            ToolDefinition(
                MEMORY_QUERY_TOOL,
                "Query the dedicated Memory Agent. If none is configured, returns memory.unavailable without failing.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "scope": {"type": "string", "default": "global"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 32, "default": 8},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            )
        )
        return tuple(tools)

    def _publication_decision(
        self,
        context: AgentContext,
        result: ModelResult,
        descriptor: CapabilityDescriptor,
    ) -> AgentDecision:
        call = result.tool_calls[0]
        text = call.arguments.get("text")
        complete_task = call.arguments.get("complete_task", True)
        if not isinstance(text, str) or not text or not isinstance(complete_task, bool):
            return AgentDecision(failure="Publication text or complete_task is invalid")
        completion_mode = "complete_on_success" if complete_task else "continue"
        continuation = result.continuation.to_dict() if result.continuation is not None else None
        if descriptor.operation == "reply":
            route_ref = self._reply_route(context, descriptor.id, descriptor.endpoint)
            if route_ref is None:
                return AgentDecision(failure="Publication reply route is unavailable")
            publication = PublicationRequest(
                "reply",
                text,
                completion_mode,
                route_ref=route_ref,
                tool_call_id=call.call_id,
                continuation=continuation,
            )
        else:
            assert descriptor.operation is not None
            destination = call.arguments.get("destination")
            reason = call.arguments.get("reason")
            if not isinstance(destination, str):
                return AgentDecision(failure="Publication destination is invalid")
            if descriptor.operation == "proactive_send" and not isinstance(reason, str):
                return AgentDecision(failure="proactive_send reason is invalid")
            publication = PublicationRequest(
                descriptor.operation,
                text,
                completion_mode,
                destination=destination,
                reason=reason if isinstance(reason, str) else None,
                tool_call_id=call.call_id,
                continuation=continuation,
            )
        return AgentDecision(publication_request=publication)

    def _safe_reply(self, context: AgentContext, text: str) -> PublicationRequest | None:
        descriptors = [
            item for item in context.capabilities if item.kind == "publication" and item.operation == "reply"
        ]
        if context.agent.parent_agent_id is not None or len(descriptors) != 1:
            return None
        descriptor = descriptors[0]
        route_ref = self._reply_route(context, descriptor.id, descriptor.endpoint)
        if route_ref is None:
            return None
        return PublicationRequest("reply", text, "complete_on_success", route_ref=route_ref)

    @staticmethod
    def _capability_tool(descriptor: CapabilityDescriptor) -> ToolDefinition:
        if descriptor.kind != "publication":
            return ToolDefinition(descriptor.id, descriptor.description, descriptor.parameters_schema)
        schema = deepcopy(descriptor.parameters_schema)
        raw_properties = schema.get("properties")
        properties = dict(raw_properties) if isinstance(raw_properties, dict) else {}
        schema["properties"] = properties
        properties["complete_task"] = {
            "type": "boolean",
            "description": "True to complete the Task after accepted delivery; false to continue afterward.",
            "default": True,
        }
        raw_required = schema.get("required")
        required = list(raw_required) if isinstance(raw_required, list) else []
        if "text" not in required:
            required.append("text")
        schema["required"] = required
        return ToolDefinition(descriptor.id, descriptor.description, schema)

    def _initial_reply_route_patch(self, context: AgentContext) -> dict[str, Any]:
        if context.message.type != "task.started":
            return {}
        replies = [item for item in context.capabilities if item.kind == "publication" and item.operation == "reply"]
        if len(replies) != 1:
            return {}
        descriptor = replies[0]
        route_ref = self._task_started_route(context, descriptor.endpoint)
        if route_ref is None:
            return {}
        return {
            "publication_reply_route": {
                "capability": descriptor.id,
                "endpoint_id": descriptor.endpoint,
                "route_ref": route_ref,
            }
        }

    def _reply_route(self, context: AgentContext, capability: str, endpoint: str | None) -> str | None:
        persisted = context.agent.state.get("publication_reply_route")
        if isinstance(persisted, dict) and (
            persisted.get("capability") == capability and persisted.get("endpoint_id") == endpoint
        ):
            route_ref = persisted.get("route_ref")
            if isinstance(route_ref, str) and route_ref:
                return route_ref
        if context.message.type == "task.started":
            return self._task_started_route(context, endpoint)
        return None

    @staticmethod
    def _task_started_route(context: AgentContext, endpoint: str | None) -> str | None:
        amp = context.message.payload.get("amp")
        payload = amp.get("payload") if isinstance(amp, dict) else None
        data = payload.get("data") if isinstance(payload, dict) else None
        communication = data.get("communication") if isinstance(data, dict) else None
        if not isinstance(communication, dict) or communication.get("endpoint_id") != endpoint:
            return None
        route_ref = communication.get("reply_route_ref")
        return route_ref if isinstance(route_ref, str) and route_ref else None
