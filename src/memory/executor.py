"""MemoryToolExecutor — 将主动记忆写入暴露为 Agent 可调用的 Tool。

主动写入与自动投影共用同一个 MemoryService：记忆同源（RFC 0207）。
幂等键为工具请求的 request_id，恢复重放由 memory_receipts 天然去重。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from src.contracts import (
    MEMORY_REMEMBER_CAPABILITY,
    CapabilityDescriptor,
    MemoryEntry,
    ToolExecutionRequest,
    ToolOutcome,
    ToolOutcomeStatus,
)

if TYPE_CHECKING:
    from src.memory.service import MemoryService


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    CONTENT_REQUIRED = "aurora.memory.remember requires a non-empty content string"
    NOT_RECORDED = "memory not recorded"
    RECORDED = "memory recorded"


MEMORY_REMEMBER_DESCRIPTOR = CapabilityDescriptor(
    id=MEMORY_REMEMBER_CAPABILITY,
    description="将一条值得长期保留的会话内容写入记忆，可同时提取可跨轮复用的稳定事实。",
    parameters_schema={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "minLength": 1,
                "description": "要记住的会话内容。",
            },
            "fact_candidates": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可跨轮复用的稳定事实，可选。",
            },
        },
        "required": ["content"],
        "additionalProperties": False,
    },
)


class MemoryToolExecutor:
    """通过同一个 MemoryService 写入记忆；scope 来自工具租约的 session_id。"""

    def __init__(self, memory: "MemoryService") -> None:
        self._memory = memory

    async def execute_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        content = request.parameters.get("content")
        if not isinstance(content, str) or not content.strip():
            return ToolOutcome(ToolOutcomeStatus.FAILED, _Msg.NOT_RECORDED, error=_Msg.CONTENT_REQUIRED)
        facts = tuple(
            str(item)
            for item in request.parameters.get("fact_candidates", ())
            if isinstance(item, str) and item.strip()
        )
        entry = MemoryEntry(
            task_id=request.request_id,
            scope=request.session_id,
            input_summary=content.strip(),
            outcome_summary=None,
            created_at=datetime.now(UTC).isoformat(),
            fact_candidates=facts,
        )
        await asyncio.to_thread(self._memory.remember, entry)
        return ToolOutcome(ToolOutcomeStatus.SUCCEEDED, _Msg.RECORDED)
