"""统一模块生命周期：按阶段激活、后台运行、排空、逆序关闭与 prepare 清理。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from src.kernel.phase import CONSTRUCTION_KINDS, PhaseKind
from src.utils import get_logger

if TYPE_CHECKING:
    from src.kernel.context import Assembly, ModuleContext
    from src.kernel.declaration import AsyncCleanup, ModuleHook, ModuleRunner
    from src.kernel.resolve import PhaseStep, Resolution

_logger = get_logger(__name__)


@dataclass(slots=True)
class ManagedAssembly:
    """持有一次已组合 Assembly 及其通用模块生命周期。"""

    assembly: Assembly
    _context: ModuleContext
    _resolution: Resolution
    _cleanups: tuple[AsyncCleanup, ...]
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)
    _activated: bool = False
    _closed: bool = False

    async def activate(self, stop: asyncio.Event) -> None:
        """按计划执行启动阶段：先运行钩子，再启动全部后台任务。"""
        if self._closed or self._activated:
            raise RuntimeError("模块生命周期只能激活一次")
        self._activated = True
        try:
            for step in self._resolution.phases:
                if step.phase.shutdown or step.phase.kind in CONSTRUCTION_KINDS:
                    continue
                await self._start(step, stop)
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        """取消后台任务，按计划执行关闭阶段，并逆序执行 prepare 清理。"""
        if self._closed:
            return
        self._closed = True
        await self._cancel_tasks()
        failures: list[Exception] = []
        for step in self._resolution.phases:
            if not step.phase.shutdown:
                continue
            await self._shutdown(step, failures)
        await self._run_cleanups(failures)
        if failures:
            raise failures[0]

    async def _start(self, step: PhaseStep, stop: asyncio.Event) -> None:
        for spec in step.modules:
            hook = spec.hook(step.phase)
            if hook is None:
                continue
            if step.phase.kind is PhaseKind.TASK:
                task = asyncio.create_task(cast("ModuleRunner", hook)(self._context, stop), name=f"aurora:{spec.name}")
                self._tasks.append(task)
            else:
                await cast("ModuleHook", hook)(self._context)

    async def _shutdown(self, step: PhaseStep, failures: list[Exception]) -> None:
        for spec in step.modules:
            hook = spec.hook(step.phase)
            if hook is None:
                continue
            try:
                await cast("ModuleHook", hook)(self._context)
            except Exception as error:  # noqa: BLE001 - 关闭必须继续释放剩余模块
                failures.append(error)

    async def _cancel_tasks(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run_cleanups(self, failures: list[Exception]) -> None:
        for cleanup in reversed(self._cleanups):
            try:
                await cleanup()
            except Exception as error:  # noqa: BLE001 - 关闭必须继续释放剩余资源
                failures.append(error)
