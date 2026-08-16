"""所有 Agent profile 共享的可恢复 Tool 链 handler。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from src.agents.base import BaseAgent
from src.contracts import (
    TOOL_EVENT_TYPES,
    AgentContext,
    AgentDecision,
    CapabilityDescriptor,
    Completion,
    ModelContinuation,
    ModelRequest,
    ModelResult,
    ToolCall,
    ToolRequest,
    append_tool_result,
)
from src.utils import get_logger

logger = get_logger("aurora.agent.tool")
_TOOL_CHAIN_STATE = "_aurora_tool_chain"


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    CAPABILITY_NO_DECISION = "capability {name} returned no decision"
    COMPLETE_TASK_BOOLEAN = "complete_task must be a boolean"
    UNKNOWN_TOOL = "unknown Tool capability {name}"


@dataclass(frozen=True, slots=True)
class _ToolChain:
    """一次模型响应中尚未完成的 Tool 调用链。"""

    call: ToolCall
    continuation: ModelContinuation | None
    remaining: tuple[ToolCall, ...] = ()
    finish_task: bool = False
    complete_on_success: bool = False

    def to_state(self) -> dict[str, object]:
        return {
            "call_id": self.call.call_id,
            "continuation": self.continuation.to_dict() if self.continuation is not None else None,
            "remaining_tool_calls": [item.to_dict() for item in self.remaining],
            "finish_task": self.finish_task,
            "complete_on_success": self.complete_on_success,
        }

    @classmethod
    def from_context(cls, context: AgentContext) -> _ToolChain | None:
        raw = context.agent.state.get(_TOOL_CHAIN_STATE)
        if not isinstance(raw, dict) or not isinstance(raw.get("call_id"), str):
            return None
        remaining = _tool_calls_from_state(raw.get("remaining_tool_calls", []))
        if remaining is None:
            return None
        raw_continuation = raw.get("continuation")
        continuation = ModelContinuation.from_dict(raw_continuation) if isinstance(raw_continuation, dict) else None
        return cls(
            ToolCall(raw["call_id"], "", {}),
            continuation,
            remaining,
            finish_task=raw.get("finish_task") is True,
            complete_on_success=raw.get("complete_on_success") is True,
        )


def _tool_calls_from_state(value: object) -> tuple[ToolCall, ...] | None:
    """恢复 Agent 状态中尚未执行的 Tool calls。"""
    if not isinstance(value, (list, tuple)):
        return None
    calls: list[ToolCall] = []
    for item in value:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("call_id"), str)
            or not isinstance(item.get("name"), str)
            or not isinstance(item.get("arguments"), dict)
        ):
            return None
        calls.append(ToolCall(item["call_id"], item["name"], dict(item["arguments"])))
    return tuple(calls)


class ToolAgent(BaseAgent):
    """围绕提供商原生 Tool IR 的确定性状态机适配器。"""

    def handle(self, context: AgentContext) -> AgentDecision:
        """Agent 入口：根据消息类型路由到对应的处理阶段。"""
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
        if message_type.startswith("child.") and isinstance(context.agent.state.get(_TOOL_CHAIN_STATE), dict):
            return self._resume_control_call(context)
        if message_type in TOOL_EVENT_TYPES:
            return self._resume_tool(context)
        return self._request_model(context)

    def _handle_model_result(self, context: AgentContext) -> AgentDecision:
        """处理模型返回结果：纯文本完成或工具调用分发。"""
        result = ModelResult.from_dict(context.message.payload)
        if not result.tool_calls:
            return AgentDecision(completion=Completion(result.text))
        return self._dispatch_tool_call(
            context, _ToolChain(result.tool_calls[0], result.continuation, result.tool_calls[1:])
        )

    def _dispatch_tool_call(
        self,
        context: AgentContext,
        chain: _ToolChain,
    ) -> AgentDecision:
        """分派一个 Tool call；同一响应的恢复信息只保存在 Agent 状态。"""
        tool_call = chain.call
        capability = self._dispatch.get(tool_call.name)
        if capability is not None:
            decision = capability.handle_tool(tool_call)
            if decision is not None:
                if decision.tool_request is not None or decision.delegations or decision.wait_for_children:
                    return self._attach_tool_chain(decision, chain)
                if decision.failure is not None:
                    return self._continue_after_local_error(context, chain, decision.failure)
                return decision
            return self._continue_after_local_error(
                context,
                chain,
                _Msg.CAPABILITY_NO_DECISION.format(name=tool_call.name),
            )
        descriptor = next((item for item in context.capabilities if item.id == tool_call.name), None)
        if descriptor is None:
            return self._continue_after_local_error(
                context,
                chain,
                _Msg.UNKNOWN_TOOL.format(name=tool_call.name),
            )
        return self._capability_decision(context, chain, descriptor)

    def _capability_decision(
        self,
        context: AgentContext,
        chain: _ToolChain,
        descriptor: CapabilityDescriptor,
    ) -> AgentDecision:
        """将模型工具调用转换为对应 ControlAction 的工具请求决策。"""
        call = chain.call
        parameters = dict(call.arguments)
        complete_task = False
        if descriptor.runtime_completion:
            complete_task = parameters.pop("complete_task", False)
            if not isinstance(complete_task, bool):
                return self._continue_after_local_error(context, chain, _Msg.COMPLETE_TASK_BOOLEAN)
        decision = AgentDecision(
            tool_request=ToolRequest(
                capability=call.name,
                parameters=parameters,
                complete_task=complete_task,
                tool_call_id=call.call_id,
            )
        )
        return self._attach_tool_chain(decision, chain)

    @staticmethod
    def _attach_tool_chain(
        decision: AgentDecision,
        chain: _ToolChain,
    ) -> AgentDecision:
        """把当前调用与剩余调用保存为一个统一、可恢复的 Agent 状态。"""
        complete_on_success = False
        if decision.tool_request is not None:
            complete_on_success = decision.tool_request.complete_task
            decision = replace(
                decision,
                tool_request=replace(decision.tool_request, complete_task=False),
            )
        state_patch = {
            **decision.state_patch,
            _TOOL_CHAIN_STATE: replace(chain, complete_on_success=complete_on_success).to_state(),
        }
        return replace(decision, state_patch=state_patch)

    def _resume_control_call(self, context: AgentContext) -> AgentDecision:
        """等待所有子 Agent 回报后，为控制 Tool 生成结果并继续剩余调用。"""
        if any(not child.terminal for child in context.children) or context.pending_child_reports:
            return AgentDecision(wait_for_children=True)
        chain = _ToolChain.from_context(context)
        if chain is None:
            return self._request_model(context)
        children = [
            {
                "agent_id": child.agent_id,
                "status": child.status,
                "summary": child.last_summary,
            }
            for child in context.children
        ]
        is_error = any(child.status == "FAILED" for child in context.children)
        continuation = chain.continuation
        if continuation is not None:
            continuation = append_tool_result(
                continuation,
                chain.call.call_id,
                {"status": "failed" if is_error else "succeeded", "children": children},
                is_error=is_error,
            )
        return self._advance_tool_chain(context, replace(chain, continuation=continuation))

    def _continue_after_local_error(
        self,
        context: AgentContext,
        chain: _ToolChain,
        error: str,
    ) -> AgentDecision:
        """把本地调用错误作为 Tool result 交还模型，不终止整个 Task。"""
        continuation = chain.continuation
        if continuation is not None:
            continuation = append_tool_result(
                continuation,
                chain.call.call_id,
                {"status": "failed", "error": error},
                is_error=True,
            )
        if continuation is None and not chain.remaining:
            return AgentDecision(failure=error)
        return self._advance_tool_chain(context, replace(chain, continuation=continuation))

    def _resume_tool(self, context: AgentContext) -> AgentDecision:
        """工具执行完成后恢复：将结果附着到延续并构造新的模型请求。"""
        chain = _ToolChain.from_context(context)
        if chain is None:
            return self._request_model(context)
        status = context.message.type.removeprefix("tool.")
        output: dict[str, object] = {"status": status}
        if status == "succeeded":
            output["result"] = context.message.payload.get("result", {})
        else:
            output["error"] = context.message.payload.get("error", status)
        continuation = chain.continuation
        if continuation is not None:
            continuation = append_tool_result(
                continuation,
                chain.call.call_id,
                output,
                is_error=status != "succeeded",
            )
        return self._advance_tool_chain(
            context,
            replace(
                chain,
                continuation=continuation,
                finish_task=chain.finish_task or (chain.complete_on_success and status == "succeeded"),
            ),
        )

    def _advance_tool_chain(
        self,
        context: AgentContext,
        chain: _ToolChain,
    ) -> AgentDecision:
        """推进统一 Tool 链；链尾才恢复模型并清除运行态。"""
        if chain.remaining:
            return self._dispatch_tool_call(
                context,
                _ToolChain(
                    chain.remaining[0],
                    chain.continuation,
                    chain.remaining[1:],
                    finish_task=chain.finish_task,
                ),
            )
        if chain.finish_task:
            decision = AgentDecision(completion=Completion(""))
        elif chain.continuation is None:
            decision = self._request_model(context)
        else:
            decision = AgentDecision(model_request=self._continuation_request(context, chain.continuation))
        return replace(decision, state_patch={**decision.state_patch, _TOOL_CHAIN_STATE: None})

    def _continuation_request(self, context: AgentContext, continuation: ModelContinuation) -> ModelRequest:
        """基于工具执行延续构造后续模型请求。"""
        request = self._request_model(context)
        assert request.model_request is not None
        return replace(
            request.model_request,
            messages=(),
            continuation=continuation,
        )
