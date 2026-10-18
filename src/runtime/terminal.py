"""本地终端文本分派：本地命令与普通消息。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import TerminalControl, TerminalResponse
from src.contracts.console import is_terminal_command
from src.utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from src.contracts import AgentTree, WorldCommit

_logger = get_logger(__name__)


class TerminalCommandDispatcher:
    """把终端文本分派为本地命令或一次 AgentTree 运行。"""

    def __init__(self, run_message: Callable[[WorldCommit], Awaitable[AgentTree]]) -> None:
        self._run_message = run_message

    async def dispatch_terminal(self, text: str, *, commit: WorldCommit | None = None) -> TerminalResponse:
        input_type = "command" if is_terminal_command(text) else "message"
        _logger.debug("终端输入开始 input_type={}", input_type)
        if text in {"/help", "/h"}:
            return TerminalResponse("本地命令：/help /clear /quit")
        if text in {"/clear", "/cls"}:
            return TerminalResponse(control=TerminalControl.CLEAR)
        if text in {"/quit", "/exit", "/q"}:
            return TerminalResponse("正在停止。", TerminalControl.SHUTDOWN)
        if is_terminal_command(text):
            return TerminalResponse("未知本地命令；输入 /help 查看命令。", is_error=True)

        if commit is None:
            raise ValueError("终端消息必须先提交到世界")
        tree = await self._run_message(commit)
        root = tree.node(tree.root_id)
        failed = root.status.value == "failed"
        rendered = root.error if failed else root.result
        _logger.debug("终端输入完成 input_type={} tree_status={}", input_type, tree.status.value)
        return TerminalResponse(rendered, is_error=failed)
