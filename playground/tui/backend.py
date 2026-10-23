"""在同一个工作线程内驱动和关闭会话，避免嵌套 Textual 的事件循环。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from playground.commands import Commands

if TYPE_CHECKING:
    from playground.session import Session


class Backend:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.commands = Commands(session)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playground-tui")
        self.closed = False

    async def request(self, text: str) -> dict[str, Any]:
        if self.closed:
            raise RuntimeError("会话已关闭")
        return await asyncio.get_running_loop().run_in_executor(self._executor, self.commands.handle, text)

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            # 已开始的调用先完成，随后在同一线程释放会话拥有的异步资源。
            await asyncio.get_running_loop().run_in_executor(self._executor, self.session.close)
        finally:
            self._executor.shutdown(wait=True)
