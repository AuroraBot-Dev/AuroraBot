"""One serial tool-capable handler shared by every RFC 0012 Agent profile."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.agents.tools import (
    capability_tool_definition,
    uses_runtime_complete_task,
)
from src.contracts.agent import (
    AgentContext,
    AgentDecision,
    CapabilityDescriptor,
    Completion,
    ToolRequest,
)
from src.contracts.model import (
    ModelContinuation,
    ModelRequest,
    ModelResult,
    ToolCall,
    ToolDefinition,
    append_tool_result,
)
from src.prompt import PromptComposer
from src.prompt.text import EMPTY_CHILD_COMPLETION, NO_ACTION_COMPLETION
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.contracts.agent import Capability

logger = get_logger("aurora.agent.tool")
_COMPOSER_ALREADY_INSTALLED = "prompt composer is already installed"
_COMPOSER_REQUIRED = "ToolAgent requires an installed PromptComposer"
_CAPABILITIES_ALREADY_INSTALLED = "capabilities are already installed"
_DUPLICATE_TOOL_IDS = "model Tool IDs must be unique"


def _collect_tool_definitions(
    context: AgentContext,
    capabilities: tuple[Capability, ...],
) -> tuple[ToolDefinition, ...]:
    tools: list[ToolDefinition] = [capability_tool_definition(item) for item in context.capabilities]
    for cap in capabilities:
        tools.extend(cap.tool_definitions(context))
    names = [tool.name for tool in tools]
    if len(names) != len(set(names)):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        message = f"{_DUPLICATE_TOOL_IDS}: {duplicates}"
        raise ValueError(message)
    return tuple(tools)


class ToolAgent:
    """A deterministic state-machine adapter around provider-native Tool IR."""

    def __init__(
        self,
        *,
        composer: PromptComposer | None = None,
        capabilities: tuple[Capability, ...] = (),
    ) -> None:
        self._composer = composer
        self._capabilities = capabilities
        self._dispatch: dict[str, Capability] = {}
        if capabilities:
            self._install_capabilities(capabilities)

    def install_prompt_composer(self, composer: PromptComposer) -> None:
        if self._composer is not None:
            raise RuntimeError(_COMPOSER_ALREADY_INSTALLED)
        self._composer = composer

    def install_capabilities(self, capabilities: tuple[Capability, ...]) -> None:
        if self._capabilities or self._dispatch:
            raise RuntimeError(_CAPABILITIES_ALREADY_INSTALLED)
        self._install_capabilities(capabilities)

    def _install_capabilities(self, capabilities: tuple[Capability, ...]) -> None:
        self._capabilities = capabilities
        for cap in capabilities:
            self._dispatch.update(dict.fromkeys(cap.tool_names, cap))

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
            response_mode="normalized",
            tools=_collect_tool_definitions(context, self._capabilities),
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
        raw = result.tool_calls[0]
        tool_call = ToolCall(raw.call_id, raw.name, raw.arguments)
        tools = _collect_tool_definitions(context, self._capabilities)
        capability = self._dispatch.get(raw.name)
        if capability is not None:
            decision = capability.handle_tool(tool_call, context, result.continuation, tools)
            if decision is not None:
                return decision
            return AgentDecision(failure=f"capability {raw.name} returned no decision")
        descriptor = next((item for item in context.capabilities if item.id == raw.name), None)
        if descriptor is None:
            return AgentDecision(failure=f"unknown Tool capability {raw.name}")
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
        output: dict[str, object] = {"status": status}
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
            response_mode="normalized",
            tools=_collect_tool_definitions(context, self._capabilities),
            continuation=continuation,
            parallel_tool_calls=False,
            cancel_policy="on_external_activity" if context.task.autonomous else "never",
        )
