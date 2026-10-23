"""记忆策略动态投影的版本和历史边界。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aurora_bot.contracts.resource import ResourceRef

_SHA256 = re.compile(r"[0-9a-f]{64}")
MEMORY_CHECKPOINT_MEDIA_TYPE = "application/vnd.aurora.memory-state+pt;version=1"


@dataclass(frozen=True, slots=True)
class MemoryGraphPrefix:
    """只有完全相同的已知交互前缀才能复用该节点投影。"""

    count: int
    cursor: int
    recorded_at: datetime
    digest: str

    def __post_init__(self) -> None:
        """游标、时间和摘要共同约束恢复边界，不能使用空图占位。"""
        if type(self.count) is not int or type(self.cursor) is not int or self.count <= 0 or self.cursor <= 0:
            raise ValueError("记忆检查点需要非空历史前缀和有效游标")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("记忆检查点的获知时间必须包含时区")
        if _SHA256.fullmatch(self.digest) is None:
            raise ValueError("记忆检查点需要确切历史的 SHA256 摘要")
        object.__setattr__(self, "recorded_at", self.recorded_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class MemoryPolicyCheckpoint:
    """固定模型版本产生的动态节点状态，不包含可训练权重。"""

    model: ResourceRef
    prefix: MemoryGraphPrefix
    content: bytes

    def __post_init__(self) -> None:
        """动态状态必须有确定的模型来源和不可变正文。"""
        if self.model.revision is None or (self.model.key.domain, self.model.key.kind) != ("memory", "model"):
            raise ValueError("记忆检查点必须绑定确定的 memory/model 版本")
        if not isinstance(self.content, bytes) or not self.content:
            raise ValueError("记忆检查点正文必须是非空 bytes")
