"""App 连接验证在失败和取消后仍须释放连接，并完整报告已知错误。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import pytest

from aurora_bot.mcp import McpToolsPage, SdkMcpClientFactory
from aurora_cli.commands.app.models import VerifyError
from aurora_cli.commands.app.verify import MCPVerifier, process_target
from tests.mcp.sdk_support import _route_stdio_to_server, _server
from tests.mcp.support import FakeClient

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_bot.mcp import McpAppSpec
    from aurora_bot.mcp.client import InboundEventHandler, McpClientPort


@dataclass(frozen=True, slots=True)
class _Factory:
    """只替换外部连接，验证与释放仍执行实际代码。"""

    client: FakeClient

    async def open(self, spec: McpAppSpec, event_handler: InboundEventHandler) -> FakeClient:
        """返回该场景控制的连接。"""
        return self.client


@pytest.mark.parametrize("discovery_error", [RuntimeError, VerifyError])
def test_discovery_and_cleanup_errors_are_both_reported_without_secrets(
    tmp_path: Path, discovery_error: type[Exception]
) -> None:
    """普通发现错误与领域错误都要释放连接，次要清理错误也必须可见。"""
    secret = "private-verifier-token"
    original = discovery_error(f"目录读取失败：{secret}")
    cleanup = OSError(f"连接关闭失败：{secret}")
    closed: list[str] = []

    class BrokenClient(FakeClient):
        """发现和关闭阶段各有独立错误。"""

        async def list_tools(self, *, cursor: str | None = None) -> McpToolsPage:
            """模拟发现失败，错误文本可能来自第三方。"""
            raise original

        async def close(self) -> None:
            """先记录真实释放尝试，再报告关闭失败。"""
            await super().close()
            raise cleanup

    client = BrokenClient("test.verify", {None: McpToolsPage(())}, closed)
    target = process_target(client.package, ("fake-server",), working_dir=tmp_path, hints=())
    target = replace(target, secrets={"SERVICE_TOKEN": secret})
    with pytest.raises(VerifyError) as captured:
        MCPVerifier(_Factory(client)).inspect(target)
    message = str(captured.value)
    assert "目录读取失败" in message
    assert "连接关闭失败" in message
    assert secret not in message
    assert closed == [client.package]
    cause = captured.value.__cause__
    assert isinstance(cause, ExceptionGroup)
    assert cause.exceptions[0].__cause__ is original
    assert cause.exceptions[1].__cause__ is cleanup


@pytest.mark.parametrize("during_close", [False, True])
def test_cancellation_waits_for_release_and_preserves_cancellation(tmp_path: Path, during_close: bool) -> None:
    """发现或关闭期间取消验证，都必须回收连接，重复取消也不能截断释放。"""

    async def scenario() -> None:
        """通过事件控制第一处取消，再由关闭动作发出第二次取消。"""
        entered = asyncio.Event()
        release = asyncio.Event()
        closed: list[str] = []
        task: asyncio.Task[object] | None = None

        class DelayedClient(FakeClient):
            """延迟指定阶段，以明确的事件控制取消点。"""

            async def list_tools(self, *, cursor: str | None = None) -> McpToolsPage:
                """发现阶段取消前已经建立连接。"""
                if not during_close:
                    entered.set()
                    await asyncio.Event().wait()
                return await super().list_tools(cursor=cursor)

            async def close(self) -> None:
                """取消后仍跨越一次异步等待并完成释放。"""
                if during_close:
                    entered.set()
                    await release.wait()
                assert task is not None
                task.cancel()
                await asyncio.sleep(0)
                await super().close()

        client = DelayedClient("test.verify", {None: McpToolsPage(())}, closed)
        target = process_target(client.package, ("fake-server",), working_dir=tmp_path, hints=())
        task = asyncio.create_task(MCPVerifier(_Factory(client)).inspect_async(target))
        await entered.wait()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()
        assert closed == [client.package]

    asyncio.run(scenario())


def test_verifier_closes_a_real_sdk_connection_before_returning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真实 SDK 使用内存传输，验证返回前连接必须完成退出。"""
    _route_stdio_to_server(monkeypatch, _server())
    opened: list[McpClientPort] = []

    class RecordingFactory:
        """仅记录实际连接，不替换 SDK 的协商与工具发现。"""

        async def open(self, spec: McpAppSpec, event_handler: InboundEventHandler) -> McpClientPort:
            """连接由正常的 SDK 工厂建立。"""
            client = await SdkMcpClientFactory().open(spec, event_handler)
            opened.append(client)
            return client

    async def scenario() -> None:
        """在事件循环仍活跃时检查连接，避免把循环退出清理误当作验证器释放。"""
        target = process_target("test.verify", ("fake-server",), working_dir=tmp_path, hints=())
        result = await MCPVerifier(RecordingFactory()).inspect_async(target)
        assert result.tool_ids == ("test.verify:tool/definition/echo",)
        assert len(opened) == 1
        assert not opened[0].connected

    asyncio.run(scenario())


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_cancellation_during_failed_discovery_cleanup_preserves_original(tmp_path: Path, cleanup_fails: bool) -> None:
    """发现失败后的清理再次被宿主取消，仍须保留最初的发现错误。"""

    async def scenario() -> None:
        """关闭任务完成后才向调用者交付取消与全部失败原因。"""
        cleaning = asyncio.Event()
        release = asyncio.Event()
        closed: list[str] = []
        original = OSError("目录服务失效")

        class BrokenClient(FakeClient):
            """发现立即失败，关闭允许在中途收到宿主取消。"""

            async def list_tools(self, *, cursor: str | None = None) -> McpToolsPage:
                """原始错误发生在已经建立连接之后。"""
                raise original

            async def close(self) -> None:
                """即使最终关闭失败，也先记录完整释放尝试。"""
                cleaning.set()
                await release.wait()
                await super().close()
                if cleanup_fails:
                    raise RuntimeError("无法确认释放结果")

        client = BrokenClient("test.verify", {None: McpToolsPage(())}, closed)
        target = process_target(client.package, ("fake-server",), working_dir=tmp_path, hints=())
        task = asyncio.create_task(MCPVerifier(_Factory(client)).inspect_async(target))
        await cleaning.wait()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError) as captured:
            await task
        assert task.cancelled()
        assert closed == [client.package]
        cause = captured.value.__cause__
        assert isinstance(cause, ExceptionGroup)
        assert cause.exceptions[0].__cause__ is original
        assert len(cause.exceptions) == 1 + cleanup_fails
        if cleanup_fails:
            assert "无法确认释放结果" in str(cause.exceptions[1])

    asyncio.run(scenario())
