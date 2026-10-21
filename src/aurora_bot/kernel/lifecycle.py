"""Bot 的装配结果视图；资源运行与释放由宿主唯一管理。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Never

if TYPE_CHECKING:
    import asyncio

    from aurora_bot.kernel.context import Assembly
    from aurora_kernel.failures import ModuleLifecycleError
    from aurora_kernel.lifecycle import ManagedAssembly as HostLifecycle


@dataclass(slots=True)
class ManagedAssembly:
    assembly: Assembly
    host: HostLifecycle

    @property
    def failures(self) -> tuple[ModuleLifecycleError, ...]:
        return self.host.failures

    async def next_failure(self) -> ModuleLifecycleError | None:
        return await self.host.next_failure()

    async def activate(self, stop: asyncio.Event) -> None:
        await self.host.activate(stop)

    async def close(self) -> None:
        await self.host.close()

    async def abort(self, error: BaseException) -> Never:
        await self.host.abort(error)
