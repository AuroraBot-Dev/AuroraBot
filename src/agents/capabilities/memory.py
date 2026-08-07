"""MemoryCapability — Agent 主动记忆写入的模型可见工具。

工具定义由记忆执行器的 catalog descriptor 单一提供（RFC 0207），
本能力只负责参数校验与 ToolRequest 构造，不持有任何存储实现。
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from src.contracts import (
    MEMORY_REMEMBER_CAPABILITY,
    AgentDecision,
    ToolDefinition,
    ToolRequest,
)

if TYPE_CHECKING:
    from src.contracts.agent import AgentContext
    from src.contracts.model import ToolCall


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    CONTENT_REQUIRED = "aurora.memory.remember requires a non-empty content string"
    FACT_CANDIDATES_INVALID = "aurora.memory.remember fact_candidates must be a list of strings"


class MemoryCapability:
    """生成 aurora.memory.remember 工具请求；执行由 MemoryToolExecutor 承担。"""

    @property
    def tool_names(self) -> frozenset[str]:
        """返回此 Capability 注册的工具名称集合。"""
        return frozenset({MEMORY_REMEMBER_CAPABILITY})

    def tool_definitions(self, context: AgentContext) -> tuple[ToolDefinition, ...]:  # noqa: ARG002
        """工具定义由 catalog descriptor 提供，避免与上下文注入重复。"""
        return ()

    def handle_tool(self, call: ToolCall) -> AgentDecision | None:
        """校验参数并生成主动记忆写入的工具请求。"""
        if call.name != MEMORY_REMEMBER_CAPABILITY:
            return None
        content = call.arguments.get("content")
        if not isinstance(content, str) or not content.strip():
            return AgentDecision(failure=_Msg.CONTENT_REQUIRED)
        raw_facts = call.arguments.get("fact_candidates") or []
        if not isinstance(raw_facts, list) or any(not isinstance(item, str) for item in raw_facts):
            return AgentDecision(failure=_Msg.FACT_CANDIDATES_INVALID)
        parameters: dict[str, object] = {"content": content}
        if raw_facts:
            parameters["fact_candidates"] = [item for item in raw_facts if item.strip()]
        return AgentDecision(
            tool_request=ToolRequest(
                capability=MEMORY_REMEMBER_CAPABILITY,
                parameters=parameters,
                tool_call_id=call.call_id,
            )
        )
