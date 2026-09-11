"""统一模块生命周期：激活、后台运行、逆序关闭与 prepare 清理。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.utils import get_logger

if TYPE_CHECKING:
    from src.kernel.context import Assembly, ModuleContext
    from src.kernel.declaration import AsyncCleanup
    from src.kernel.resolve import Resolution

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
        """按激活依赖激活模块，并启动所有后台 run hook。"""
        if self._closed or self._activated:
            raise RuntimeError("模块生命周期只能激活一次")
        self._activated = True
        try:
            for spec in self._resolution.activation:
                if spec.activate is not None:
                    await spec.activate(self._context)
            self._tasks.extend(
                asyncio.create_task(spec.run(self._context, stop), name=f"aurora:{spec.name}")
                for spec in self._resolution.activation
                if spec.run is not None
            )
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        """取消后台任务，并逆序关闭模块与 prepare 资源。"""
        if self._closed:
            return
        self._closed = True
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        failures: list[Exception] = []
        for spec in reversed(self._resolution.construction):
            if spec.close is None:
                continue
            try:
                await spec.close(self._context)
            except Exception as error:  # noqa: BLE001 - 关闭必须继续释放剩余模块
                failures.append(error)
        for cleanup in reversed(self._cleanups):
            try:
                await cleanup()
            except Exception as error:  # noqa: BLE001 - 关闭必须继续释放剩余资源
                failures.append(error)
        if failures:
            raise failures[0]
