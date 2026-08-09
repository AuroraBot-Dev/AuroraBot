"""MemoryToolExecutor — 主动记忆写入工具执行器。

主动写入与自动投影共用同一个 MemoryService（同源）；执行完成后经
注入的 AMP 入口提交 tool.succeeded 回执。
幂等：request_id 由 engine 的活动幂等键保证回执去重。
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from src.contracts import (
    MEMORY_REMEMBER_CAPABILITY,
    CapabilityDescriptor,
    MemoryEntry,
    ToolExecutionRequest,
    tool_receipt_amp,
)
from src.utils import utc_now

if TYPE_CHECKING:
    from src.contracts.ports import ExternalAmpIngressPort
    from src.memory.service import MemoryService


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    CONTENT_REQUIRED = "aur.serv.memory.remember requires a non-empty content string"
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
    """通过同一个 MemoryService 写入记忆；scope 来自工具请求的 session_id。"""

    def __init__(self, memory: "MemoryService", ingress: "ExternalAmpIngressPort") -> None:
        self._memory = memory
        self._ingress = ingress

    async def execute_tool(self, request: ToolExecutionRequest) -> None:
        content = request.parameters.get("content")
        if not isinstance(content, str) or not content.strip():
            await self._submit(request, "failed", _Msg.NOT_RECORDED, error=_Msg.CONTENT_REQUIRED)
            return
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
            created_at=utc_now(),
            fact_candidates=facts,
        )
        await self._memory.remember(entry)
        await self._submit(request, "succeeded", _Msg.RECORDED)

    async def _submit(
        self,
        request: ToolExecutionRequest,
        status: str,
        summary: str,
        *,
        result: dict[str, object] | None = None,
        error: str | None = None,
    ) -> None:
        await self._ingress.submit_amp(
            tool_receipt_amp(
                status=status,
                request=request,
                summary=summary,
                source_app="memory",
                source_instance="local",
                result=result,
                error=error,
            )
        )
