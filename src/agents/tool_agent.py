"""One serial tool-capable handler shared by every RFC 0012 Agent profile."""

from __future__ import annotations

import json

from src.agents.tools import (
    CLAIM_TOOL,
    DELEGATE_TOOL,
    MEMORY_QUERY_TOOL,
    MEMORY_REMEMBER_TOOL,
    WAIT_TOOL,
    build_tool_definitions,
    uses_runtime_complete_task,
)
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
    ModelRequest,
    ModelResult,
    append_tool_result,
)
from src.prompt import PromptComposer
from src.prompt.text import EMPTY_CHILD_COMPLETION, NO_ACTION_COMPLETION
from src.utils.log_utils import get_logger

logger = get_logger("aurora.agent.tool")
_COMPOSER_ALREADY_INSTALLED = "prompt composer is already installed"
_COMPOSER_REQUIRED = "ToolAgent requires an installed PromptComposer"


class ToolAgent:
    """A deterministic state-machine adapter around provider-native Tool IR."""

    def __init__(self, *, composer: PromptComposer | None = None) -> None:
        self._composer = composer

    def install_prompt_composer(self, composer: PromptComposer) -> None:
        if self._composer is not None:
            raise RuntimeError(_COMPOSER_ALREADY_INSTALLED)
        self._composer = composer

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
        composer = self._require_composer()
        request = ModelRequest(
            role=context.profile.model_role,
            messages=composer.request_messages(context),
            required_capabilities=frozenset({"chat", "tools"}),
            response_mode="native" if context.profile.model_role == "agent" else "normalized",
            tools=build_tool_definitions(context),
            parallel_tool_calls=False,
            cancel_policy="on_external_activity" if context.task.autonomous else "never",
        )
        return AgentDecision(model_request=request.to_dict())

    def _require_composer(self) -> PromptComposer:
        if self._composer is None:
            raise RuntimeError(_COMPOSER_REQUIRED)
        return self._composer

    def _handle_model_result(self, context: AgentContext) -> AgentDecision:
        result = ModelResult.from_dict(context.message.payload)
        if len(result.tool_calls) > 1:
            return AgentDecision(failure="parallel_tool_calls_rejected")
        if not result.tool_calls:
            text = result.text.strip()
            if context.agent.parent_agent_id is not None:
                return AgentDecision(completion=Completion(text or EMPTY_CHILD_COMPLETION))
            return AgentDecision(completion=Completion(text or NO_ACTION_COMPLETION, silent=not bool(text)))
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
        if call.name == MEMORY_REMEMBER_TOOL:
            return self._handle_memory_remember(context, result)
        descriptor = next((item for item in context.capabilities if item.id == call.name), None)
        if descriptor is None:
            return AgentDecision(failure=f"unknown Tool capability {call.name}")
        return self._capability_decision(result, descriptor)

    def _capability_decision(self, result: ModelResult, descriptor: CapabilityDescriptor) -> AgentDecision:
        call = result.tool_calls[0]
        parameters = dict(call.arguments)
        complete_task = False
        if uses_runtime_complete_task(descriptor):
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

    def _handle_memory_remember(self, context: AgentContext, result: ModelResult) -> AgentDecision:
        call = result.tool_calls[0]
        content = call.arguments.get("content")
        if not isinstance(content, str) or not content.strip():
            return AgentDecision(failure="memory.remember content must be a non-empty string")
        if context.memory_agent_profile is not None:
            return AgentDecision(
                delegations=(
                    DelegationRequest(
                        json.dumps({"type": "memory.proposal", "content": content}, ensure_ascii=False),
                        context.memory_agent_profile,
                    ),
                )
            )
        continuation = result.continuation
        if continuation is None:
            return AgentDecision(completion=Completion("remembered", silent=True))
        continuation = append_tool_result(continuation, call.call_id, {"ok": True, "stored": False}, is_error=False)
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
            tools=build_tool_definitions(context),
            continuation=continuation,
            parallel_tool_calls=False,
            cancel_policy="on_external_activity" if context.task.autonomous else "never",
        )
