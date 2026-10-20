"""Bot 的时间服务契约，状态选择仍属于主体状态存储。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import asyncio
    from datetime import datetime

    from aurorabot.contracts.pkgs.runtime import TreeLauncher


class BotClock(Protocol):
    """兑现 Bot 已经选择的未来活动安排。"""

    def bind_launcher(self, launcher: TreeLauncher) -> None:
        """绑定当前进程的认知运行入口。"""
        ...

    async def initialize(self) -> None:
        """核对重启前已经开始的安排。"""
        ...

    async def evaluate_once(self, now: datetime | None = None) -> None:
        """检查并兑现最多一次到期安排。"""
        ...

    async def run(self, stop: asyncio.Event) -> None:
        """持续检查时间，直到停止。"""
        ...
