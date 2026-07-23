"""提供 aurora.memory.query 和 aurora.memory.remember 工具的 Capability。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.contracts.agent import AgentDecision, Completion, DelegationRequest
from src.contracts.memory import MemoryFailure, MemoryQuery
from src.contracts.model import (
    ModelContinuation,
    ModelRequest,
    ToolDefinition,
    append_tool_result,
)

if TYPE_CHECKING:
    from src.contracts.agent import AgentContext
    from src.contracts.model import ToolCall

MEMORY_QUERY_TOOL = "aurora.memory.query"
MEMORY_REMEMBER_TOOL = "aurora.memory.remember"

_QUERY_DESCRIPTION = "向记忆 Agent 询问过去留下的线索；没有配置记忆 Agent 时会平静地返回不可用。"
_REMEMBER_DESCRIPTION = "把现在知道的重要事情记下来，下次需要的时候可以从记忆里找回来。"

_QUERY_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "我想从过往寻找什么。"},
        "scope": {"type": "string", "default": "global", "description": "寻找记忆的范围。"},
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 32,
            "default": 8,
            "description": "最多带回多少条线索。",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}

_REMEMBER_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "content": {"type": "string", "description": "我想要记住的事情。"},
        "importance": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "default": 0.5,
            "description": "这件事的重要性，1为最重要。",
        },
    },
    "required": ["content"],
    "additionalProperties": False,
}


class MemoryCapability:
    """模型通过 aurora.memory.query/remember 读写长期记忆。"""

    def __init__(self, *, memory_service: Any = None, agent_profile: str | None = None) -> None:
        """初始化 MemoryCapability。

        Args:
            memory_service: 记忆服务实例。
            agent_profile: 记忆 Agent 的 profile ID，存在时启用 remember 工具并走委派路径。
        """
        self._memory = memory_service
        self._agent_profile = agent_profile

    @property
    def tool_names(self) -> frozenset[str]:
        """返回此 Capability 注册的工具名称集合。"""
        return frozenset({MEMORY_QUERY_TOOL, MEMORY_REMEMBER_TOOL})

    def tool_definitions(self, context: AgentContext) -> tuple[ToolDefinition, ...]:  # noqa: ARG002
        """返回记忆工具定义，remember 工具仅在配置了 agent_profile 时提供。"""
        tools = [ToolDefinition(MEMORY_QUERY_TOOL, _QUERY_DESCRIPTION, _QUERY_SCHEMA)]
        if self._agent_profile is not None:
            tools.append(ToolDefinition(MEMORY_REMEMBER_TOOL, _REMEMBER_DESCRIPTION, _REMEMBER_SCHEMA))
        return tuple(tools)

    def handle_tool(
        self,
        call: ToolCall,
        context: AgentContext,
        continuation: object = None,
        tools: tuple[object, ...] = (),
    ) -> AgentDecision | None:
        """根据工具名称分发到查询或记忆处理。"""
        if call.name == MEMORY_QUERY_TOOL:
            return self._handle_query(call, context, continuation, tools)
        if call.name == MEMORY_REMEMBER_TOOL:
            return self._handle_remember(call, context, continuation, tools)
        return None

    def _handle_query(
        self,
        call: ToolCall,
        context: AgentContext,
        continuation: object,
        tools: tuple[object, ...],
    ) -> AgentDecision:
        """处理记忆查询：走委派路径或直接返回不可用结果。"""
        query = call.arguments.get("query")
        scope = call.arguments.get("scope", "global")
        limit = call.arguments.get("limit", 8)
        valid_limit = isinstance(limit, int) and not isinstance(limit, bool) and 1 <= limit <= 32  # noqa: PLR2004
        if not isinstance(query, str) or not isinstance(scope, str) or not valid_limit:
            return AgentDecision(failure="memory query is invalid")
        memory_query = MemoryQuery(query, scope, limit)
        if self._agent_profile is not None:
            return AgentDecision(
                delegations=(
                    DelegationRequest(
                        json.dumps({"type": "memory.query", **memory_query.to_dict()}, ensure_ascii=False),
                        self._agent_profile,
                    ),
                )
            )
        if not isinstance(continuation, ModelContinuation):
            return AgentDecision(failure="memory query requires model continuation")
        continuation = append_tool_result(
            continuation,
            call.call_id,
            {"ok": False, **MemoryFailure().to_dict()},
            is_error=False,
        )
        request = self._continuation_request(context, continuation, tools)
        return AgentDecision(model_request=request.to_dict())

    def _handle_remember(
        self,
        call: ToolCall,
        context: AgentContext,
        continuation: object,
        tools: tuple[object, ...],
    ) -> AgentDecision:
        """处理记忆存储：走委派路径或直接返回已存储结果。"""
        content = call.arguments.get("content")
        if not isinstance(content, str) or not content.strip():
            return AgentDecision(failure="memory.remember content must be a non-empty string")
        if self._agent_profile is not None:
            return AgentDecision(
                delegations=(
                    DelegationRequest(
                        json.dumps({"type": "memory.proposal", "content": content}, ensure_ascii=False),
                        self._agent_profile,
                    ),
                )
            )
        if not isinstance(continuation, ModelContinuation):
            return AgentDecision(completion=Completion("remembered", silent=True))
        continuation = append_tool_result(continuation, call.call_id, {"ok": True, "stored": False}, is_error=False)
        request = self._continuation_request(context, continuation, tools)
        return AgentDecision(model_request=request.to_dict())

    def _continuation_request(
        self, context: AgentContext, continuation: ModelContinuation, tools: tuple[object, ...]
    ) -> ModelRequest:
        """基于工具执行延续构造后续模型请求。"""
        return ModelRequest(
            role=context.profile.model_role,
            messages=(),
            required_capabilities=frozenset({"chat", "tools"}),
            response_mode="normalized",
            tools=tuple(t for t in tools if isinstance(t, ToolDefinition)),
            continuation=continuation,
            parallel_tool_calls=False,
            cancel_policy="on_external_activity" if context.task.autonomous else "never",
        )
