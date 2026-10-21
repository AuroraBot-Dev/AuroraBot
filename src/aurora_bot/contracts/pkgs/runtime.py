"""``runtime`` 暴露的全局端口：认知唤起与终端分派契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from aurora_bot.contracts.cognition import CognitionRequest, CognitionResult
    from aurora_bot.contracts.console import TerminalResponse
    from aurora_bot.contracts.world import WorldCommit


class CognitionLauncher(Protocol):
    """接受一次认知唤起请求的运行时端口。"""

    async def launch(self, request: CognitionRequest) -> CognitionResult: ...


class TerminalDispatcher(Protocol):
    """把一次终端文本分派为本地命令或一次认知运行。"""

    async def dispatch_terminal(self, text: str, *, commit: WorldCommit | None = None) -> TerminalResponse: ...
