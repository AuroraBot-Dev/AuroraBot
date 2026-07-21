"""One serial tool-capable handler shared by every RFC 0012 Agent profile."""

from __future__ import annotations

import json
import re
from copy import deepcopy

from src.contracts.agent import (
    AgentContext,
    AgentDecision,
    CapabilityDescriptor,
    Completion,
    DelegationRequest,
    ToolRequest,
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
            return AgentDecision(failure=error)
        if message_type in {"tool.succeeded", "tool.failed", "tool.unknown"}:
            return self._resume_tool(context)
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
                "Use the available tools for external actions.",
                "Delegate only independent, bounded work that materially helps this task.",
                "A child result is evidence for you to continue working, not the final user response.",
                "Set complete_task=true only when this Tool success should finish your current work.",
            ],
        }
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
        return AgentDecision(model_request=request.to_dict())

    def _handle_model_result(self, context: AgentContext) -> AgentDecision:
        result = ModelResult.from_dict(context.message.payload)
        if len(result.tool_calls) > 1:
            return AgentDecision(failure="parallel_tool_calls_rejected")
        if not result.tool_calls:
            text = result.text.strip()
            if context.agent.parent_agent_id is not None:
                return AgentDecision(completion=Completion(text or "Subtask completed without a textual result"))
            return AgentDecision(completion=Completion(text or "no_action", silent=not bool(text)))
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
        descriptor = next((item for item in context.capabilities if item.id == call.name), None)
        if descriptor is None:
            return AgentDecision(failure=f"unknown Tool capability {call.name}")
        return self._capability_decision(result, descriptor)

    def _capability_decision(self, result: ModelResult, descriptor: CapabilityDescriptor) -> AgentDecision:
        call = result.tool_calls[0]
        parameters = dict(call.arguments)
        complete_task = False
        if not self._defines_complete_task(descriptor):
            complete_task = parameters.pop("complete_task", False)
            if not isinstance(complete_task, bool):
                return AgentDecision(failure="complete_task must be a boolean")
        return AgentDecision(
            tool_request=ToolRequest(
                capability=call.name,
                parameters=parameters,
                complete_task=complete_task,
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

    def _resume_tool(self, context: AgentContext) -> AgentDecision:
        request = context.message.payload.get("request")
        if not isinstance(request, dict):
            return AgentDecision(failure="Tool receipt lacks original request")
        raw_continuation = request.get("continuation")
        call_id = request.get("tool_call_id")
        if not isinstance(raw_continuation, dict) or not isinstance(call_id, str):
            return self._request_model(context)
        continuation = ModelContinuation.from_dict(raw_continuation)
        status = context.message.type.removeprefix("tool.")
        output = {"status": status}
        if status == "succeeded":
            output["result"] = context.message.payload.get("result", {})
        else:
            output["error"] = context.message.payload.get("error", status)
        continuation = append_tool_result(continuation, call_id, output, is_error=status != "succeeded")
        model_request = self._continuation_request(context, continuation)
        return AgentDecision(model_request=model_request.to_dict())

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

    @staticmethod
    def _capability_tool(descriptor: CapabilityDescriptor) -> ToolDefinition:
        schema = deepcopy(descriptor.parameters_schema)
        if ToolAgent._defines_complete_task(descriptor):
            return ToolDefinition(descriptor.id, descriptor.description, schema)
        raw_properties = schema.get("properties")
        properties = dict(raw_properties) if isinstance(raw_properties, dict) else {}
        schema["properties"] = properties
        properties["complete_task"] = {
            "type": "boolean",
            "description": "Complete this Agent's current work after the Tool succeeds.",
            "default": False,
        }
        return ToolDefinition(descriptor.id, descriptor.description, schema)

    @staticmethod
    def _defines_complete_task(descriptor: CapabilityDescriptor) -> bool:
        return _schema_defines_complete_task(descriptor.parameters_schema, descriptor.parameters_schema, set())


def _schema_defines_complete_task(schema: object, root: dict[str, object], seen: set[int]) -> bool:
    if not isinstance(schema, dict) or id(schema) in seen:
        return False
    seen.add(id(schema))
    properties = schema.get("properties")
    if isinstance(properties, dict) and "complete_task" in properties:
        return True
    patterns = schema.get("patternProperties")
    if isinstance(patterns, dict):
        for pattern in patterns:
            try:
                if re.search(str(pattern), "complete_task"):
                    return True
            except re.error:
                continue
    reference = schema.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/"):
        target: object = root
        for raw_part in reference[2:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                target = None
                break
            target = target[part]
        if _schema_defines_complete_task(target, root, seen):
            return True
    for keyword in ("allOf", "anyOf", "oneOf"):
        branches = schema.get(keyword)
        if isinstance(branches, list) and any(_schema_defines_complete_task(branch, root, seen) for branch in branches):
            return True
    return False
