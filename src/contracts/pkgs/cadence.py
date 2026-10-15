"""``cadence`` 暴露的全局端口：世界驱动主动节律契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import asyncio

    from src.contracts.pkgs.runtime import TreeLauncher


class Cadence(Protocol):
    """世界提交驱动的主动节律。"""

    agent: str | None

    @property
    def enabled(self) -> bool: ...

    def status(self) -> dict[str, object]: ...

    async def initialize(self) -> None: ...

    async def evaluate_once(self) -> None: ...

    async def run(self, stop_event: asyncio.Event) -> None: ...

    def bind_launcher(self, launcher: TreeLauncher) -> None: ...
