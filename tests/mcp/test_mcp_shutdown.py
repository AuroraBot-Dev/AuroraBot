"""MCP 多连接清理必须继续释放，并将每项失败交给宿主。"""

from __future__ import annotations

import asyncio

import pytest

from aurorabot.mcp import McpAppState, McpCloseError, McpStartupError, McpToolsPage, prepare_mcp
from tests.mcp.support import FakeClient, FakeFactory, FakeWorld, _spec, _tool


@pytest.mark.parametrize("self_cancelled", [False, True])
def test_close_preserves_every_client_failure_and_continues_releasing(self_cancelled: bool) -> None:
    """单连接关闭异常或主动取消都不能吞掉错误或跳过其余连接。"""

    async def scenario() -> None:
        """两个连接出错，一个连接正常，按逆序全部释放。"""
        order: list[str] = []

        class BrokenClient(FakeClient):
            """释放完成后返回该连接自己的关闭错误。"""

            async def close(self) -> None:
                """取消是连接自身的结果，不是宿主取消。"""
                await super().close()
                if self_cancelled:
                    raise asyncio.CancelledError("连接自行取消关闭")
                raise OSError("连接释放失败")

        clients = (
            FakeClient("test.good", {None: McpToolsPage(())}, order),
            BrokenClient("test.first", {None: McpToolsPage(())}, order),
            BrokenClient("test.second", {None: McpToolsPage(())}, order),
        )
        runtime = await prepare_mcp(
            tuple(_spec(client.package) for client in clients),
            platform_enabled=True,
            world=FakeWorld(),
            factory=FakeFactory({client.package: client for client in clients}),
        )
        with pytest.raises(ExceptionGroup) as captured:
            await runtime.close()
        assert order == ["test.second", "test.first", "test.good"]
        errors = captured.value.exceptions
        assert len(errors) == len(clients) - 1
        assert "test.second" in str(errors[0])
        assert "test.first" in str(errors[1])
        expected_type = asyncio.CancelledError if self_cancelled else OSError
        assert all(isinstance(error.__cause__, expected_type) for error in errors)
        states = {app.package: app.state.value for app in runtime.snapshot().apps}
        assert states == {"test.good": "closed", "test.first": "close_failed", "test.second": "close_failed"}
        await runtime.close()
        assert order == ["test.second", "test.first", "test.good"]

    asyncio.run(scenario())


def test_startup_failure_is_preserved_together_with_cleanup_failure() -> None:
    """目录发现已经失败时，随后关闭失败不能掩盖原始启动原因。"""

    async def scenario() -> None:
        """失败连接先关闭，前面已连接的依赖仍需释放。"""
        order: list[str] = []

        class BrokenClient(FakeClient):
            """发现和关闭分别产生不同的错误。"""

            async def close(self) -> None:
                """关闭也失败，仍需保留前面的发现错误。"""
                await super().close()
                raise OSError("释放失败")

        first = FakeClient("test.first", {None: McpToolsPage(())}, order)
        second = BrokenClient("test.second", {None: McpToolsPage((_tool("invalid", schema_type="array"),))}, order)
        with pytest.raises(ExceptionGroup) as captured:
            await prepare_mcp(
                (_spec(first.package), _spec(second.package)),
                platform_enabled=True,
                world=FakeWorld(),
                factory=FakeFactory({client.package: client for client in (first, second)}),
            )
        assert isinstance(captured.value.exceptions[0], McpStartupError)
        assert "释放失败" in str(captured.value.exceptions[1])
        assert order == [second.package, first.package]

    asyncio.run(scenario())


def test_cancelled_close_finishes_every_connection_and_remains_cancelled() -> None:
    """宿主取消不应截断当前连接的释放或跳过剩余连接。"""

    async def scenario() -> None:
        """精确在最后一个连接释放中连续取消两次关闭调用者。"""
        entered = asyncio.Event()
        release = asyncio.Event()
        order: list[str] = []
        closer: asyncio.Task[None] | None = None

        class DelayedClient(FakeClient):
            """真实异步清理跨越取消时刻。"""

            async def close(self) -> None:
                """再次取消宿主不能打断随后其他连接的释放。"""
                entered.set()
                await release.wait()
                assert closer is not None
                closer.cancel()
                await super().close()

        first = FakeClient("test.first", {None: McpToolsPage(())}, order)
        second = DelayedClient("test.second", {None: McpToolsPage(())}, order)
        runtime = await prepare_mcp(
            (_spec(first.package), _spec(second.package)),
            platform_enabled=True,
            world=FakeWorld(),
            factory=FakeFactory({client.package: client for client in (first, second)}),
        )
        closer = asyncio.create_task(runtime.close())
        await entered.wait()
        closer.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await closer
        assert closer.cancelled()
        assert order == [second.package, first.package]
        assert all(app.state is McpAppState.CLOSED for app in runtime.snapshot().apps)
        await runtime.close()

    asyncio.run(scenario())


def test_failed_event_deactivation_still_closes_all_clients() -> None:
    """停止事件入口失败时仍须关闭连接，报告中能区分实际失败阶段。"""

    async def scenario() -> None:
        """事件停止错误不会被之后正常的资源关闭覆盖。"""
        order: list[str] = []
        original = ValueError("无法停止事件入口")

        class BrokenEventsClient(FakeClient):
            """停止事件出错，实际连接关闭仍然可以成功。"""

            def deactivate_events(self) -> None:
                """让同步错误也经过继续清理与完整报告。"""
                raise original

        first = BrokenEventsClient("test.first", {None: McpToolsPage(())}, order)
        second = FakeClient("test.second", {None: McpToolsPage(())}, order)
        runtime = await prepare_mcp(
            (_spec(first.package), _spec(second.package)),
            platform_enabled=True,
            world=FakeWorld(),
            factory=FakeFactory({client.package: client for client in (first, second)}),
        )
        with pytest.raises(McpCloseError) as captured:
            await runtime.close()
        assert captured.value.package == first.package
        assert captured.value.phase == "deactivate"
        assert captured.value.error is original
        assert order == [second.package, first.package]
        assert all(app.state is McpAppState.CLOSED for app in runtime.snapshot().apps)
        await runtime.close()

    asyncio.run(scenario())
