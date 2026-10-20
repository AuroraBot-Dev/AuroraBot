"""Bot 主体状态的读取与原子提交契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from aurorabot.contracts.pkgs.clock import BotClock

if TYPE_CHECKING:
    from aurorabot.contracts.bot import BotChange, BotSnapshot

__all__ = ["BotClock", "BotStateStore"]


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
