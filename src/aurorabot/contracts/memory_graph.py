"""时序记忆推荐的节点、交互与评分输入；监督标签另行保存。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import datetime

MEMORY_RELATIONS = ("experience", "scope", "goal", "entity", "depends_on", "supersedes", "useful", "unhelpful")
MEMORY_NODE_KINDS = ("memory", "scope", "goal", "entity")
MemoryNodeKind = Literal["memory", "scope", "goal", "entity"]


@dataclass(frozen=True, slots=True)
class MemoryNode:
    """有类型的图节点身份，文本只来自该交互当时已知的内容。"""

    kind: MemoryNodeKind
    identity: str
    text: str = ""

    def __post_init__(self) -> None:
        """类型参与身份，避免目标和经历使用同名时合并。"""
        if self.kind not in MEMORY_NODE_KINDS or not self.identity.strip():
            raise ValueError("记忆图节点需要有效类型和非空身份")

    @property
    def key(self) -> tuple[str, str]:
        """提供无歧义的状态索引，不依赖拼接字符串。"""
        return self.kind, self.identity


@dataclass(frozen=True, slots=True)
class MemoryInteraction:
    """一次已知的图交互；游标决定可见性，获知时间决定时间间隔。"""

    cursor: int
    recorded_at: datetime
    source: MemoryNode
    target: MemoryNode
    relation: str
    value: float = 1.0

    def __post_init__(self) -> None:
        """关系坐标固定，训练与在线推理不能各自解释一套词表。"""
        if self.cursor <= 0 or self.relation not in MEMORY_RELATIONS or not math.isfinite(self.value):
            raise ValueError("记忆交互的游标、关系或取值无效")
        _aware(self.recorded_at)


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """一个可读取记忆点及可解释基线特征。"""

    memory_id: str
    text: str
    cursor: int
    occurred_at: datetime
    recorded_at: datetime
    similarity: float = 0.0
    goal_match: bool = False
    entity_match: bool = False

    def __post_init__(self) -> None:
        """候选必须来自真实可追溯经历。"""
        if not self.memory_id.strip() or self.cursor <= 0 or not 0 <= self.similarity <= 1:
            raise ValueError("记忆候选的身份、游标或相似度无效")
        _aware(self.occurred_at)
        _aware(self.recorded_at)


@dataclass(frozen=True, slots=True)
class MemoryRankingRequest:
    """在同一知识前缀上比较候选；结果反馈不能穿越到评分输入。"""

    query: str
    focus_goal_ids: tuple[str, ...]
    cursor: int
    observed_at: datetime
    candidates: tuple[MemoryCandidate, ...]
    interactions: tuple[MemoryInteraction, ...] = ()

    def __post_init__(self) -> None:
        """拒绝未来候选、未来图边和乱序经历。"""
        _aware(self.observed_at)
        for field in ("focus_goal_ids", "candidates", "interactions"):
            object.__setattr__(self, field, tuple(getattr(self, field)))
        if self.cursor < 0 or len({item.memory_id for item in self.candidates}) != len(self.candidates):
            raise ValueError("记忆评分需要非负游标和不重复的候选")
        if any(
            item.cursor > self.cursor or item.recorded_at > self.observed_at or item.occurred_at > self.observed_at
            for item in self.candidates
        ):
            raise ValueError("记忆评分不能读取未来候选")
        previous_cursor = 0
        previous_time = None
        for event in self.interactions:
            if event.cursor > self.cursor or event.recorded_at > self.observed_at:
                raise ValueError("记忆评分不能读取未来反馈或交互")
            if event.cursor < previous_cursor or (previous_time is not None and event.recorded_at < previous_time):
                raise ValueError("记忆图交互必须按获知顺序排列")
            previous_cursor, previous_time = event.cursor, event.recorded_at

    def ranked_indices(self, scores: tuple[float, ...]) -> tuple[int, ...]:
        """在线与离线共用排序，等分时优先最近获知的候选。"""
        if len(scores) != len(self.candidates) or any(not math.isfinite(score) for score in scores):
            raise ValueError("记忆策略必须为每个候选返回有限评分")
        return tuple(
            sorted(
                range(len(scores)),
                key=lambda index: (-scores[index], -self.candidates[index].cursor, self.candidates[index].memory_id),
            )
        )


def _aware(value: datetime) -> None:
    """所有跨历史边界的时间均带时区。"""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("记忆图时间必须包含时区")
