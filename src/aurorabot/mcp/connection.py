"""由一个任务拥有 MCP 连接的完整上下文，避免跨任务退出取消作用域。"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING

from aurorabot.utils import get_logger
from aurorabot.utils.tasks import raise_with_cleanup, wait_for_completion

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aurorabot.mcp.client import McpClientPort

_logger = get_logger(__name__)


class McpConnection:
    """调用者可以跨任务使用连接，资源的进入和退出始终属于同一任务。"""

    def __init__(self) -> None:
        """在当前事件循环创建就绪与关闭信号。"""
        self._ready: asyncio.Future[McpClientPort] = asyncio.get_running_loop().create_future()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def open(self, connect: Callable[[AsyncExitStack], Awaitable[McpClientPort]]) -> McpClientPort:
        """只有连接握手完成才返回；启动取消或失败也等待所属任务回收。"""
        if self._task is not None:
            raise RuntimeError("MCP 连接所属任务只能启动一次")
        self._task = asyncio.create_task(self._run(connect), name="aurora:mcp:connection")
        self._task.add_done_callback(_retrieve_exception)
        try:
            return await asyncio.shield(self._ready)
        except BaseException as error:
            _logger.exception("MCP 连接未能就绪，等待资源释放")
            self._stop.set()
            if not self._ready.done():
                self._task.cancel()
            outcomes, interrupted = await wait_for_completion(asyncio.gather(self._task, return_exceptions=True))
            if not self._ready.done():
                self._ready.cancel()
            elif not self._ready.cancelled():
                self._ready.exception()
            failures = [
                outcome
                for outcome in outcomes
                if isinstance(outcome, BaseException) and not isinstance(outcome, asyncio.CancelledError)
            ]
            raise_with_cleanup(error, failures, interrupted)

    async def aclose(self) -> None:
        """请求所属任务退出上下文，调用者取消不会中断资源释放。"""
        self._stop.set()
        if self._task is not None:
            outcomes, interrupted = await wait_for_completion(asyncio.gather(self._task, return_exceptions=True))
            failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
            if interrupted is not None:
                raise_with_cleanup(interrupted, failures)
            if failures:
                raise failures[0]

    async def _run(self, connect: Callable[[AsyncExitStack], Awaitable[McpClientPort]]) -> None:
        """创建连接并持续保有其上下文，关闭信号到达后在本任务退出。"""
        failure: BaseException | None = None
        try:
            async with AsyncExitStack() as resources:
                try:
                    client = await connect(resources)
                    self._ready.set_result(client)
                    await self._stop.wait()
                except BaseException as error:
                    _logger.exception("MCP 连接运行失败，开始释放资源")
                    failure = error
            if failure is not None:
                raise failure
        except BaseException as error:
            _logger.exception("MCP 连接所属任务失败")
            if failure is not None and failure is not error:
                error = BaseExceptionGroup("MCP 连接与资源释放同时失败", [failure, error])
            if not self._ready.done():
                self._ready.set_exception(error)
            raise error


def _retrieve_exception(task: asyncio.Task[None]) -> None:
    """失败已记录且保留在任务结果中，主动回收通知以避免遗漏警告。"""
    if not task.cancelled():
        task.exception()
