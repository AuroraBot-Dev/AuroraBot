from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from aurora_agent import RunSnapshot
    from aurora_bot.contracts.cognition import CognitionRequest, CognitionResult
    from aurora_bot.contracts.process import CognitionProcess


class CognitionRunner(Protocol):
    """执行请求并持久记录开始、结果；中断保留未确认效果供恢复核对。"""

    @property
    def process_definition(self) -> CognitionProcess: ...

    async def execute(
        self, request: CognitionRequest, observer: Callable[[RunSnapshot], None] | None = None
    ) -> CognitionResult: ...
