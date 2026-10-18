"""``runtime`` 暴露的全局端口：AgentTree 唤起与终端分派契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.contracts.agent import AgentTree, TreeLaunchRequest
    from src.contracts.console import TerminalResponse
    from src.contracts.world import WorldCommit


class TreeLauncher(Protocol):
    """接受一次 AgentTree 唤起请求的运行时端口。"""

    async def launch_tree(self, request: TreeLaunchRequest) -> AgentTree: ...


class TerminalDispatcher(Protocol):
    """把一次终端文本分派为本地命令或一次 AgentTree 运行。"""

    async def dispatch_terminal(self, text: str, *, commit: WorldCommit | None = None) -> TerminalResponse: ...
