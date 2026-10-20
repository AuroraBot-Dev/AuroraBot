"""关闭过程被取消或被多个调用者等待时，资源仍应完整且只释放一次。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from aurorabot.kernel import ModuleLifecycleError, compose_managed, module
from tests.kernel_support import Settings as _Settings

if TYPE_CHECKING:
    from aurorabot.kernel import AsyncCleanup, ModuleContext


def test_concurrent_close_waits_for_the_same_resource_release() -> None:
    """后来的关闭调用不能在第一次释放尚未结束时提前返回。"""

    async def scenario() -> None:
        """由事件控制关闭进度，不依赖执行耗时。"""
        entered = asyncio.Event()
        release = asyncio.Event()
        second_started = asyncio.Event()
        trace: list[str] = []

        async def close(context: ModuleContext) -> None:
            """资源尚未释放时保持挂起。"""
            trace.append("close.started")
            entered.set()
            await release.wait()
            trace.append("close.finished")

        @module(name="resource", provides=int, close=close)
        def build(context: ModuleContext) -> int:
            """提供一个独立模组用于控制释放过程。"""
            return 1

        handle = await compose_managed(_Settings(), (build,))
        first = asyncio.create_task(handle.close())
        await entered.wait()

        async def second_close() -> None:
            """通知测试已经开始第二次关闭请求。"""
            second_started.set()
            await handle.close()

        second = asyncio.create_task(second_close())
        await second_started.wait()
        try:
            assert not second.done()
        finally:
            release.set()
            await asyncio.gather(first, second)
        assert trace == ["close.started", "close.finished"]

    asyncio.run(scenario())


@pytest.mark.parametrize("repeated", [False, True])
def test_cancellation_waits_for_every_cleanup_and_then_remains_cancelled(repeated: bool) -> None:
    """取消请求不应截断关闭；再次取消也不能跳过后续准备资源释放。"""

    async def scenario() -> None:
        """精确在一个关闭钩子挂起时取消调用者。"""
        entered = asyncio.Event()
        release = asyncio.Event()
        trace: list[str] = []
        closer: asyncio.Task[None] | None = None

        async def prepare(context: ModuleContext) -> AsyncCleanup:
            """准备阶段得到的资源也必须完成释放。"""

            async def cleanup() -> None:
                """后续清理不能被前一个钩子收到取消而跳过。"""
                trace.append("prepare.cleaned")

            return cleanup

        async def close(context: ModuleContext) -> None:
            """第一次取消后，还可在释放期间收到第二次取消。"""
            entered.set()
            await release.wait()
            if repeated:
                assert closer is not None
                closer.cancel()
            trace.append("close.finished")

        @module(name="resource", provides=int, prepare=prepare, close=close)
        def build(context: ModuleContext) -> int:
            """构造正常，测试只改变关闭调用者状态。"""
            return 1

        handle = await compose_managed(_Settings(), (build,))
        closer = asyncio.create_task(handle.close())
        await entered.wait()
        closer.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await closer
        assert closer.cancelled()
        assert trace == ["close.finished", "prepare.cleaned"]
        await handle.close()
        assert trace == ["close.finished", "prepare.cleaned"]

    asyncio.run(scenario())


def test_abort_keeps_the_original_failure_when_cancelled_during_cleanup() -> None:
    """故障后的释放被取消时，取消语义与原始故障都需保留。"""

    async def scenario() -> None:
        """只有关闭钩子启动之后才发送取消。"""
        entered = asyncio.Event()
        release = asyncio.Event()
        original = ValueError("原始运行失败")

        async def close(context: ModuleContext) -> None:
            """等待测试允许释放结束。"""
            entered.set()
            await release.wait()

        @module(name="resource", provides=int, close=close)
        def build(context: ModuleContext) -> int:
            """运行失败由宿主传入，不来自构造。"""
            return 1

        handle = await compose_managed(_Settings(), (build,))
        closer = asyncio.create_task(handle.abort(original))
        await entered.wait()
        closer.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError) as captured:
            await closer
        cause = captured.value.__cause__
        assert isinstance(cause, BaseExceptionGroup)
        assert original in cause.exceptions

    asyncio.run(scenario())


def test_cancelled_close_preserves_cleanup_failure_and_finishes_remaining_resources() -> None:
    """取消仍是外层结果，清理错误作为原因保留且不妨碍剩余资源释放。"""

    async def scenario() -> None:
        """取消关闭调用者后，再让资源释放返回真实错误。"""
        entered = asyncio.Event()
        release = asyncio.Event()
        cleaned = asyncio.Event()
        original = OSError("资源释放失败")

        async def prepare(context: ModuleContext) -> AsyncCleanup:
            """后置释放结果用于证明错误没有截断清理。"""

            async def cleanup() -> None:
                """记录准备资源已释放。"""
                cleaned.set()

            return cleanup

        async def close(context: ModuleContext) -> None:
            """取消之后产生的释放错误也必须保留。"""
            entered.set()
            await release.wait()
            raise original

        @module(name="resource", provides=int, prepare=prepare, close=close)
        def build(context: ModuleContext) -> int:
            """构造过程不影响取消场景。"""
            return 1

        handle = await compose_managed(_Settings(), (build,))
        closer = asyncio.create_task(handle.close())
        await entered.wait()
        closer.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError) as captured:
            await closer
        assert cleaned.is_set()
        cause = captured.value.__cause__
        assert isinstance(cause, ExceptionGroup)
        assert len(cause.exceptions) == 1
        failure = cause.exceptions[0]
        assert isinstance(failure, ModuleLifecycleError)
        assert failure.error is original
        await handle.close()

    asyncio.run(scenario())


def test_cancelled_waiter_cannot_interrupt_another_close() -> None:
    """并发关闭时取消其中一个等待者，不会取消共享的释放任务。"""

    async def scenario() -> None:
        """两个调用者在同一个关闭钩子完成后分别返回各自结果。"""
        entered = asyncio.Event()
        release = asyncio.Event()
        second_started = asyncio.Event()
        released: list[str] = []

        async def close(context: ModuleContext) -> None:
            """只释放一次资源。"""
            entered.set()
            await release.wait()
            released.append("done")

        @module(name="resource", provides=int, close=close)
        def build(context: ModuleContext) -> int:
            """提供可控制关闭时机的资源。"""
            return 1

        handle = await compose_managed(_Settings(), (build,))
        first = asyncio.create_task(handle.close())
        await entered.wait()

        async def second_close() -> None:
            """先告知测试等待者已开始，再等待关闭结果。"""
            second_started.set()
            await handle.close()

        second = asyncio.create_task(second_close())
        await second_started.wait()
        second.cancel()
        release.set()
        outcomes = await asyncio.gather(first, second, return_exceptions=True)
        assert outcomes[0] is None
        assert isinstance(outcomes[1], asyncio.CancelledError)
        assert released == ["done"]

    asyncio.run(scenario())


@pytest.mark.parametrize("initially_cancelled", [False, True])
def test_cancellation_during_construction_rollback_finishes_all_resources(initially_cancelled: bool) -> None:
    """构造回滚也必须抵御取消，保留原始错误并释放全部已获得的资源。"""

    async def scenario() -> None:
        """在已构造资源的关闭中取消装配任务。"""
        entered = asyncio.Event()
        release = asyncio.Event()
        trace: list[str] = []
        original = asyncio.CancelledError("构造被取消") if initially_cancelled else ValueError("构造失败")

        async def prepare(context: ModuleContext) -> AsyncCleanup:
            """准备资源需要在构造回滚之后释放。"""

            async def cleanup() -> None:
                """记录准备资源释放完成。"""
                trace.append("prepare.cleaned")

            return cleanup

        async def close(context: ModuleContext) -> None:
            """只延迟已构造资源的释放。"""
            entered.set()
            await release.wait()
            trace.append("close.finished")

        @module(name="resource", provides=str, prepare=prepare, close=close)
        def resource(context: ModuleContext) -> str:
            """先构造需要回收的依赖资源。"""
            return "ready"

        @module(name="broken", provides=int, requires=str)
        def broken(context: ModuleContext) -> int:
            """取得依赖之后才发生原始构造错误。"""
            raise original

        task = asyncio.create_task(compose_managed(_Settings(), (resource, broken)))
        await entered.wait()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError) as captured:
            await task
        assert task.cancelled()
        assert trace == ["close.finished", "prepare.cleaned"]
        if initially_cancelled:
            assert captured.value is original
        else:
            cause = captured.value.__cause__
            assert isinstance(cause, BaseExceptionGroup)
            assert original in cause.exceptions

    asyncio.run(scenario())
