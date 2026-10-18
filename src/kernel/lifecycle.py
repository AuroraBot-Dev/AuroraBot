"""监督模组后台故障，并按声明顺序完成关闭和资源释放。"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from src.kernel.context import _ModuleContext
from src.kernel.failures import ModuleCleanup, ModuleLifecycleError, collect_failure, raise_failures, raise_with_cleanup
from src.kernel.phase import CONSTRUCTION_KINDS, PhaseKind
from src.utils import get_logger
from src.utils.tasks import wait_for_completion

if TYPE_CHECKING:
    from typing import Never

    from src.kernel.context import Assembly, ModuleContext
    from src.kernel.declaration import ModuleHook, ModuleRunner
    from src.kernel.resolve import PhaseStep, Resolution

_logger = get_logger(__name__)


@dataclass(slots=True)
class ManagedAssembly:
    """故障交给宿主处理；尚未交付的故障由关闭流程报告。"""

    assembly: Assembly
    _context: ModuleContext
    _resolution: Resolution
    _cleanups: tuple[ModuleCleanup, ...]
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)
    _failures: list[ModuleLifecycleError] = field(default_factory=list)
    _pending: deque[ModuleLifecycleError] = field(default_factory=deque)
    _changed: asyncio.Event = field(default_factory=asyncio.Event)
    _closing: asyncio.Task[list[Exception]] | None = None
    _activated: bool = False
    _closed: bool = False

    @property
    def failures(self) -> tuple[ModuleLifecycleError, ...]:
        """返回完整的后台故障历史，读取快照不表示已处理故障。"""
        return tuple(self._failures)

    async def next_failure(self) -> ModuleLifecycleError | None:
        """等待并取走下一项故障；关闭且没有待交付故障时返回空值。"""
        while not self._pending:
            if self._closed:
                return None
            await self._changed.wait()
            self._changed.clear()
        return self._pending.popleft()

    async def activate(self, stop: asyncio.Event) -> None:
        """按计划执行启动钩子，后台任务的错误始终保留在监督通道。"""
        if self._closed or self._activated:
            raise RuntimeError("模块生命周期只能激活一次")
        self._activated = True
        try:
            for step in self._resolution.phases:
                if step.phase.shutdown or step.phase.kind in CONSTRUCTION_KINDS:
                    continue
                await self._start(step, stop)
        except BaseException as error:
            _logger.exception("模组激活失败，开始关闭")
            await self.abort(error)

    async def close(self) -> None:
        """回收后台、报告未交付故障，并释放全部关闭钩子与准备资源。"""
        failures, interrupted = await self._close()
        if interrupted is not None:
            raise_with_cleanup(interrupted, failures)
        raise_failures(failures)

    async def abort(self, error: BaseException) -> Never:
        """运行已经失败时完成同样的清理，同时保留原始错误。"""
        failures, interrupted = await self._close()
        raise_with_cleanup(error, failures, interrupted)

    async def _close(self) -> tuple[list[Exception], asyncio.CancelledError | None]:
        """所有调用者等待同一次释放，调用者的取消延迟到资源回收结束。"""
        owner = self._closing is None
        if self._closing is None:
            self._closed = True
            self._changed.set()
            self._closing = asyncio.create_task(self._release(), name="aurora:shutdown")
        failures, interrupted = await wait_for_completion(self._closing)
        return (failures if owner else []), interrupted

    async def _release(self) -> list[Exception]:
        """释放任务独立于调用者的取消，依次收集全部资源的清理结果。"""
        await self._cancel_tasks()
        failures: list[Exception] = list(self._pending)
        self._pending.clear()
        for step in self._resolution.phases:
            if step.phase.shutdown:
                await self._shutdown(step, failures)
        for cleanup in reversed(self._cleanups):
            failure = await cleanup.run()
            if failure is not None:
                failures.append(failure)
        return failures

    async def _start(self, step: PhaseStep, stop: asyncio.Event) -> None:
        """任务与普通钩子使用同一模块能力视图。"""
        for spec in step.modules:
            hook = spec.hook(step.phase)
            if hook is None:
                continue
            bound = _ModuleContext(self._context, spec.name, self._resolution.providers)
            if step.phase.kind is PhaseKind.TASK:
                task = asyncio.create_task(
                    self._run_module(spec.name, step.phase.name, cast("ModuleRunner", hook), bound, stop),
                    name=f"aurora:{spec.name}:{step.phase.name}",
                )
                task.add_done_callback(_retrieve_exception)
                self._tasks.append(task)
            else:
                await cast("ModuleHook", hook)(bound)

    async def _run_module(
        self, module_name: str, phase_name: str, runner: ModuleRunner, context: ModuleContext, stop: asyncio.Event
    ) -> None:
        """正常停止不记为故障，意外取消与运行异常立即交给宿主。"""
        try:
            await runner(context, stop)
        except asyncio.CancelledError as error:
            if not self._closed and not stop.is_set():
                self._record_failure(module_name, phase_name, error)
            raise
        except BaseException as error:
            self._record_failure(module_name, phase_name, error)
            raise

    def _record_failure(self, module_name: str, phase_name: str, error: BaseException) -> None:
        """故障先保留到历史与待处理队列，再唤醒监督者。"""
        failure = ModuleLifecycleError(module_name, phase_name, error)
        self._failures.append(failure)
        self._pending.append(failure)
        self._changed.set()
        _logger.error("模组后台失败 module={} phase={} error_type={}", module_name, phase_name, type(error).__name__)

    async def _shutdown(self, step: PhaseStep, failures: list[Exception]) -> None:
        """单个关闭钩子失败不能阻止剩余模组释放。"""
        for spec in step.modules:
            hook = spec.hook(step.phase)
            if hook is None:
                continue
            bound = _ModuleContext(self._context, spec.name, self._resolution.providers)
            failure = await collect_failure(spec.name, step.phase.name, cast("ModuleHook", hook)(bound))
            if failure is not None:
                failures.append(failure)

    async def _cancel_tasks(self) -> None:
        """等待已启动任务的清理结束，运行异常由监督通道保留。"""
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


def _retrieve_exception(task: asyncio.Task[None]) -> None:
    """故障已显式进入监督通道，及时回收任务异常而不产生未读取警告。"""
    if not task.cancelled():
        task.exception()
