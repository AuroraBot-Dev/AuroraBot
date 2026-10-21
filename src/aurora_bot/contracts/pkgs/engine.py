"""认知执行端口：调用方不需要创建或理解执行器的委派结构。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from aurora_bot.contracts.agent import AgentNode
    from aurora_bot.contracts.cognition import CognitionRequest, CognitionResult
    from aurora_bot.contracts.process import CognitionProcess
    from aurora_bot.contracts.tool import ToolDefinition


class CognitionRunner(Protocol):
    """执行请求并持久记录开始、结果；中断保留未确认效果供恢复核对。"""

    @property
    def process_definition(self) -> CognitionProcess: ...

    @property
    def tool_definitions(self) -> tuple[ToolDefinition, ...]: ...

    async def execute(
        self, request: CognitionRequest, observer: Callable[[tuple[AgentNode, ...]], None] | None = None
    ) -> CognitionResult: ...
