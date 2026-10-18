"""``memory`` 暴露的全局端口：世界记忆快照的只读契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.contracts.memory import MemoryRequest
    from src.contracts.memory_graph import MemoryRankingRequest
    from src.contracts.resource import ResourceRef
    from src.contracts.world import MemorySnapshot


class MemoryReader(Protocol):
    """按活跃 scope 提供世界记忆快照的只读端口。"""

    async def recall(self, request: MemoryRequest | None = None) -> MemorySnapshot: ...


class MemoryPolicy(Protocol):
    """固定权重的记忆排序策略，图状态由输入历史决定。"""

    @property
    def ref(self) -> ResourceRef: ...

    @property
    def parameters(self) -> dict[str, float | int]: ...

    def score(self, request: MemoryRankingRequest) -> tuple[float, ...]: ...
