"""让停止信号、前台与模组故障共同控制一次 Bot 进程运行。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

from aurorabot.contracts import WorldFrontier
from aurorabot.runtime.events import RUNTIME_MODULE_FAILED, RUNTIME_SCOPE
from aurorabot.utils import get_logger
from aurorabot.utils.tasks import wait_for_completion

if TYPE_CHECKING:
    from aurorabot.contracts import Front
    from aurorabot.kernel import ManagedAssembly
    from aurorabot.runtime.core import AuroraRuntime

_logger = get_logger(__name__)


async def supervise(
    runtime: AuroraRuntime, lifecycle: ManagedAssembly, fronts: tuple[Front, ...], stop: asyncio.Event
) -> None:
    """任一故障或停止信号到达后，先回收前台，再让宿主关闭模组资源。"""
    claimed = asyncio.Event()
    monitor = asyncio.create_task(_observe_modules(runtime, lifecycle, claimed), name="aurora:module-supervisor")
    tasks = [
        monitor,
        asyncio.create_task(stop.wait(), name="aurora:stop-supervisor"),
    ]
    if fronts:
        tasks.append(asyncio.create_task(_run_fronts(fronts, stop), name="aurora:front-supervisor"))
    interrupted = None
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError as error:
        interrupted = error
    stop.set()
    for task in tasks:
        if not task.done() and (task is not monitor or not claimed.is_set()):
            task.cancel()
    outcomes, later_interruption = await wait_for_completion(asyncio.gather(*tasks, return_exceptions=True))
    interrupted = interrupted or later_interruption
    failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    if interrupted is not None:
        if failures:
            raise interrupted from ExceptionGroup("停止运行时协作者时发生错误", failures)
        raise interrupted
    if len(failures) == 1:
        raise failures[0]
    if failures:
        raise ExceptionGroup("运行时协作者发生多个错误", failures)


async def _run_fronts(fronts: tuple[Front, ...], stop: asyncio.Event) -> None:
    """一个前台失败时取消并等待其他前台，资源关闭前不留运行任务。"""
    async with asyncio.TaskGroup() as group:
        for index, front in enumerate(fronts):
            group.create_task(_run_front(front, stop, index), name=f"aurora:front:{index}")


async def _run_front(front: Front, stop: asyncio.Event, index: int) -> None:
    """未请求停止的主动取消属于前台故障。"""
    try:
        await front.run(stop)
    except asyncio.CancelledError as error:
        if not stop.is_set():
            stop.set()
            raise RuntimeError(f"前台 {index} 在停止前意外取消") from error
        raise
    except BaseException:
        stop.set()
        raise


async def _observe_modules(runtime: AuroraRuntime, lifecycle: ManagedAssembly, claimed: asyncio.Event) -> None:
    """把首次后台故障提交到 Bot 世界，再交给进程运行者处理。"""
    failure = await lifecycle.next_failure()
    if failure is None:
        return
    claimed.set()
    try:
        await runtime.world.append_commit(
            commit_id=f"runtime:module-failure:{uuid4().hex}",
            kind=RUNTIME_MODULE_FAILED,
            source="runtime",
            summary=str(failure),
            scopes=frozenset({RUNTIME_SCOPE}),
            based_on=WorldFrontier(),
            data={
                "module": failure.module_name,
                "phase": failure.phase_name,
                "error_type": type(failure.error).__name__,
                "message": str(failure.error),
            },
        )
    except Exception as error:
        _logger.exception("模组故障无法提交到世界")
        raise ExceptionGroup("模组运行与故障记录同时失败", [failure, error]) from None
    raise failure
