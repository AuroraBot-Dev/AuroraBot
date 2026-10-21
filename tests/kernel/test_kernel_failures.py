"""模组后台故障必须可观察，关闭仍需释放其余资源。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from aurora_bot.kernel import ModuleLifecycleError, compose_managed, module
from tests.kernel.support import Settings as _Settings

_EXPECTED_RELEASE_ERRORS = 2

if TYPE_CHECKING:
    from aurora_bot.kernel import AsyncCleanup, ModuleContext


def test_background_failure_is_not_discarded_when_closing() -> None:
    """后台已经失败时，关闭不能只回收异常并宣称成功。"""

    async def scenario() -> None:
        """使用真实后台任务复现故障被关闭流程丢弃。"""
        started = asyncio.Event()

        async def run(context: ModuleContext, stop: asyncio.Event) -> None:
            """故障来自实际运行阶段，无需定时等待或环境依赖。"""
            started.set()
            raise ValueError("失去连接")

        @module(name="poller", provides=int, run=run)
        def build(context: ModuleContext) -> int:
            """纯构造不影响后台失败。"""
            return 1

        handle = await compose_managed(_Settings(), (build,))
        await handle.activate(asyncio.Event())
        await started.wait()
        with pytest.raises(RuntimeError, match=r"poller.*run.*失去连接"):
            await handle.close()

    asyncio.run(scenario())


def test_failure_can_be_delivered_before_close_without_losing_its_history() -> None:
    """宿主已经取走的故障不在关闭时重复抛出，历史仍完整可读。"""

    async def run(context: ModuleContext, stop: asyncio.Event) -> None:
        """后台失败先于宿主开始读取。"""
        raise ValueError("传感器断开")

    @module(name="sensor", provides=int, run=run)
    def build(context: ModuleContext) -> int:
        """服务类型只用于独立装配。"""
        return 1

    async def scenario() -> None:
        """等待有事件驱动，不依赖轮询或固定睡眠。"""
        handle = await compose_managed(_Settings(), (build,))
        await handle.activate(asyncio.Event())
        async with asyncio.timeout(1):
            failure = await handle.next_failure()
        assert failure is not None
        assert (failure.module_name, failure.phase_name) == ("aurora:kernel/module/sensor", "run")
        assert isinstance(failure.error, ValueError)
        assert failure.__cause__ is failure.error
        assert handle.failures == (failure,)
        await handle.close()
        assert await handle.next_failure() is None
        assert handle.failures == (failure,)

    asyncio.run(scenario())


def test_close_reports_all_hook_and_prepare_cleanup_errors() -> None:
    """一个释放失败不阻止其他释放，报告中保留每个模组和阶段。"""
    trace = []

    async def prepare(context: ModuleContext) -> AsyncCleanup:
        """准备资源带有自己的逆序清理动作。"""

        async def cleanup() -> None:
            """模拟连接关闭失败。"""
            trace.append("cleanup")
            raise OSError("连接释放失败")

        return cleanup

    async def close(context: ModuleContext) -> None:
        """模拟关闭钩子失败。"""
        trace.append("close")
        raise ValueError("关闭失败")

    @module(name="resources", provides=int, prepare=prepare, close=close)
    def build(context: ModuleContext) -> int:
        """构造阶段正常。"""
        return 1

    async def scenario() -> None:
        """所有错误都应被保留，第二次关闭不再次释放。"""
        handle = await compose_managed(_Settings(), (build,))
        with pytest.raises(ExceptionGroup) as captured:
            await handle.close()
        errors = captured.value.exceptions
        assert len(errors) == _EXPECTED_RELEASE_ERRORS
        assert all(isinstance(error, ModuleLifecycleError) for error in errors)
        assert [error.phase_name for error in errors if isinstance(error, ModuleLifecycleError)] == ["close", "prepare"]
        await handle.close()
        assert trace == ["close", "cleanup"]

    asyncio.run(scenario())


@pytest.mark.parametrize("construction", [False, True])
def test_startup_error_and_cleanup_error_are_both_preserved(construction: bool) -> None:
    """回滚和激活失败均不能被随后发生的释放错误覆盖。"""
    original = ValueError("原始启动失败")

    async def prepare(context: ModuleContext) -> AsyncCleanup:
        """资源已取得，因此失败后仍需清理。"""

        async def cleanup() -> None:
            """释放过程也有独立失败。"""
            raise OSError("清理失败")

        return cleanup

    async def activate(context: ModuleContext) -> None:
        """在实际激活阶段触发原始错误。"""
        raise original

    @module(name="startup", provides=int, prepare=prepare, activate=activate)
    def build(context: ModuleContext) -> int:
        """也可选择在实际构造阶段失败。"""
        if construction:
            raise original
        return 1

    async def scenario() -> None:
        """异常组保持原始对象身份与后续释放错误。"""
        with pytest.raises(ExceptionGroup) as captured:
            handle = await compose_managed(_Settings(), (build,))
            await handle.activate(asyncio.Event())
        assert captured.value.exceptions[0] is original
        cleanup_error = captured.value.exceptions[1]
        assert isinstance(cleanup_error, ModuleLifecycleError)
        assert cleanup_error.module_name == "aurora:kernel/module/startup"
        assert isinstance(cleanup_error.error, OSError)

    asyncio.run(scenario())


@pytest.mark.parametrize("requested_stop", [False, True])
def test_unexpected_cancellation_is_reported_but_requested_stop_is_normal(requested_stop: bool) -> None:
    """任务主动取消不能悄悄丢失能力，正常停止则不制造故障。"""

    async def run(context: ModuleContext, stop: asyncio.Event) -> None:
        """用明确的停止事件区分取消原因。"""
        if requested_stop:
            stop.set()
        raise asyncio.CancelledError("取消运行")

    @module(name="cancelled", provides=int, run=run)
    def build(context: ModuleContext) -> int:
        """构造与取消语义互不干扰。"""
        return 1

    async def scenario() -> None:
        """等待任务完成后检查故障通道。"""
        stop = asyncio.Event()
        handle = await compose_managed(_Settings(), (build,))
        await handle.activate(stop)
        if requested_stop:
            await stop.wait()
            await handle.close()
            assert handle.failures == ()
        else:
            async with asyncio.timeout(1):
                failure = await handle.next_failure()
            assert failure is not None and isinstance(failure.error, asyncio.CancelledError)
            await handle.close()

    asyncio.run(scenario())


def test_close_wakes_a_host_waiting_for_failure() -> None:
    """正常关闭没有故障时，等待者也能结束而不泄漏监督任务。"""

    @module(name="idle", provides=int)
    def build(context: ModuleContext) -> int:
        """此组合没有后台任务。"""
        return 1

    async def scenario() -> None:
        """关闭前后都可安全读取已耗尽的故障通道。"""
        handle = await compose_managed(_Settings(), (build,))
        waiter = asyncio.create_task(handle.next_failure())
        await handle.close()
        async with asyncio.timeout(1):
            assert await waiter is None

    asyncio.run(scenario())
