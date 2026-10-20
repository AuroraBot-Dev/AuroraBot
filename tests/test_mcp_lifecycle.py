"""真实 MCP SDK 连接必须在所属任务中释放，不能跨任务退出取消作用域。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import anyio
from test_kernel import _Settings
from test_mcp_sdk_client import _ignore_event, _route_stdio_to_server, _server, _stdio_spec

from aurorabot.kernel import compose_managed, module
from aurorabot.mcp import SdkMcpClientFactory
from aurorabot.mcp.connection import McpConnection

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from contextlib import AsyncExitStack
    from pathlib import Path

    import pytest

    from aurorabot.kernel import AsyncCleanup, ModuleContext
    from aurorabot.mcp.client import McpClientPort


def test_kernel_can_release_a_real_sdk_connection_from_its_cleanup_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """通过真实 SDK 的内存传输覆盖完整装配和独立关闭任务。"""
    _route_stdio_to_server(monkeypatch, _server())

    async def prepare(context: ModuleContext) -> AsyncCleanup:
        """准备时建立真实连接，返回实际关闭动作。"""
        client = await SdkMcpClientFactory().open(_stdio_spec(tmp_path), _ignore_event)
        page = await client.list_tools()
        assert [tool.name for tool in page.tools] == ["echo"]
        return client.close

    @module(name="connection", provides=int, prepare=prepare)
    def build(context: ModuleContext) -> int:
        """使用独立能力避免依赖项目级配置。"""
        return 1

    async def scenario() -> None:
        """关闭中的取消作用域不能取消构造调用者。"""
        handle = await compose_managed(_Settings(), (build,))
        await handle.close()

    asyncio.run(scenario())


def test_repeated_startup_cancellation_waits_for_task_owned_resources() -> None:
    """连接尚未就绪时取消启动，也必须在所属任务完成全部资源释放。"""

    async def scenario() -> None:
        """真实 AnyIO 作用域与阻塞清理覆盖启动时连续两次取消。"""
        started = asyncio.Event()
        cleaning = asyncio.Event()
        release = asyncio.Event()
        trace: list[str] = []

        @asynccontextmanager
        async def resource() -> AsyncIterator[None]:
            """上下文退出必须仍由创建资源的任务执行。"""
            owner = asyncio.current_task()
            trace.append("entered")
            try:
                yield
            finally:
                cleaning.set()
                await release.wait()
                assert asyncio.current_task() is owner
                trace.append("released")

        async def connect(resources: AsyncExitStack) -> McpClientPort:
            """握手阻塞期间已经建立了任务所属的连接资源。"""
            await resources.enter_async_context(resource())
            await resources.enter_async_context(anyio.create_task_group())
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("未完成握手的连接不能返回")

        task = asyncio.create_task(McpConnection().open(connect))
        async with asyncio.timeout(3):
            await started.wait()
            task.cancel()
            await cleaning.wait()
            task.cancel()
            release.set()
            try:
                await task
            except asyncio.CancelledError:
                assert task.cancelled()
            else:
                raise AssertionError("启动调用必须保留取消结果")
        assert trace == ["entered", "released"]

    asyncio.run(scenario())
