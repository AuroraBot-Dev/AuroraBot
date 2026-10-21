"""``console`` 暴露的全局端口：本地终端前端契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable

    from aurora_bot.contracts.pkgs.runtime import TerminalDispatcher


class TerminalConsole(Protocol):
    """本地终端前端。"""

    async def run(
        self,
        dispatcher: TerminalDispatcher,
        *,
        stop_event: asyncio.Event | None = None,
        readline: Callable[[str], str] | None = None,
        output: Callable[[str], None] = print,
    ) -> None: ...
