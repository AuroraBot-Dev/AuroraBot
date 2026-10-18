"""``memory`` 暴露的全局端口：世界记忆快照的只读契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.contracts.memory import MemoryRequest
    from src.contracts.world import MemorySnapshot


class MemoryReader(Protocol):
    """按活跃 scope 提供世界记忆快照的只读端口。"""

    async def recall(self, request: MemoryRequest | None = None) -> MemorySnapshot: ...
