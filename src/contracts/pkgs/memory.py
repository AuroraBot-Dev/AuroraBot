"""``memory`` 暴露的全局端口：世界记忆快照的只读契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Mapping

    from src.contracts.artifact import ArtifactInfo
    from src.contracts.memory import MemoryRequest
    from src.contracts.memory_checkpoint import MemoryPolicyCheckpoint
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
    def parameters(self) -> Mapping[str, float | int]: ...

    def score(self, request: MemoryRankingRequest) -> tuple[float, ...]: ...


class MemoryPolicyState(Protocol):
    """固定版本策略可选择保存动态投影，恢复后仍需核对实际查询历史。"""

    @property
    def ref(self) -> ResourceRef: ...

    def checkpoint(self, *, after: str | None = None) -> MemoryPolicyCheckpoint | None: ...

    def restore(self, checkpoint: MemoryPolicyCheckpoint) -> bool: ...


class MemoryCheckpoints(Protocol):
    """为 Bot 持久化可重建的策略投影，失败时保持原始世界事实可用。"""

    async def initialize(self) -> bool: ...

    async def save(self) -> ArtifactInfo | None: ...

    async def run(self, stop: asyncio.Event) -> None: ...
