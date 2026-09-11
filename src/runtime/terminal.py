"""本地终端文本分派：本地命令与普通消息。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import TerminalControl, TerminalResponse
from src.utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from src.contracts import AgentTree

_logger = get_logger(__name__)


class TerminalCommandDispatcher:
    """把终端文本分派为本地命令或一次 AgentTree 运行。"""

    def __init__(
        self,
        run_message: Callable[[str], Awaitable[AgentTree]],
        *,
        serve_panel: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        self._run_message = run_message
        self._serve_panel = serve_panel

    def bind_serve_panel(self, serve_panel: Callable[[], Awaitable[str]] | None) -> None:
        self._serve_panel = serve_panel

    async def dispatch_terminal(self, text: str) -> TerminalResponse:
        input_type = "command" if text.startswith("/") else "message"
        _logger.debug("终端输入开始 input_type={}", input_type)
        if text in {"/help", "/h"}:
            return TerminalResponse("本地命令：/help /clear /quit /serve")
        if text in {"/clear", "/cls"}:
            return TerminalResponse(control=TerminalControl.CLEAR)
        if text in {"/quit", "/exit", "/q"}:
            return TerminalResponse("正在停止。", TerminalControl.SHUTDOWN)
        if text == "/serve":
            return await self._serve()
        if text.startswith("/"):
            return TerminalResponse("未知本地命令；输入 /help 查看命令。", is_error=True)

        tree = await self._run_message(text)
        root = tree.node(tree.root_id)
        failed = root.status.value == "failed"
        rendered = root.error if failed else root.result
        _logger.debug("终端输入完成 input_type={} tree_status={}", input_type, tree.status.value)
        return TerminalResponse(rendered, is_error=failed)

    async def _serve(self) -> TerminalResponse:
        if self._serve_panel is None:
            return TerminalResponse("Panel 后端当前不可启动。", is_error=True)
        try:
            return TerminalResponse(await self._serve_panel())
        except (OSError, RuntimeError, ValueError) as error:
            _logger.error("Panel 后端启动失败 error_type={}", type(error).__name__)
            return TerminalResponse(f"Panel 后端启动失败：{error}", is_error=True)
