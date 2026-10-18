"""Bot 主体状态的读取与原子提交契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import asyncio
    from datetime import datetime

    from src.contracts.bot import BotChange, BotSnapshot
    from src.contracts.pkgs.runtime import TreeLauncher


class BotStateStore(Protocol):
    """从持久经历恢复主体，并以显式版本保护选择。"""

    @property
    def bot_id(self) -> str:
        """返回长期稳定的 Bot 身份。"""
        ...

    @property
    def scope(self) -> str:
        """返回主体状态所属的世界域。"""
        ...

    async def snapshot(self) -> BotSnapshot:
        """读取包括最新持久提交的主体快照。"""
        ...

    async def snapshot_at(self, cursor: int) -> BotSnapshot:
        """只恢复截至某个世界游标已经存在的主体选择。"""
        ...

    async def apply(self, change: BotChange) -> BotSnapshot:
        """原子提交修改，重复命令不重复产生效果。"""
        ...


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
