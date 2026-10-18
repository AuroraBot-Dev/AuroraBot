"""记忆读取的显式任务条件和历史可见边界。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from src.contracts.identity import Identifier

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from src.contracts.bot import Goal, WakePlan
    from src.contracts.resource import ResourceRef
    from src.contracts.world import WorldCommit


@dataclass(frozen=True, slots=True)
class MemoryBundle:
    """应共同进入上下文的一组经历，依赖和替代关系不能被预算拆散。"""

    commits: tuple[WorldCommit, ...]
    score: float
    routes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryContinuity:
    """本次工作所需的完整状态，以及未展开主体内容的明确概览。"""

    bot_id: str
    version: int
    goals: tuple[Goal, ...] = ()
    wakes: tuple[WakePlan, ...] = ()
    goal_counts: tuple[tuple[str, int], ...] = ()
    wake_counts: tuple[tuple[str, int], ...] = ()
    missing_goal_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryRequest:
    """在确定的获知边界内，为当前任务选择经历。"""

    query: str = ""
    focus_goal_ids: tuple[str, ...] = ()
    scopes: frozenset[str] | None = None
    cursor: int | None = None
    observed_at: datetime | None = None
    max_characters: int = 8000

    def __post_init__(self) -> None:
        """固定任务条件，拒绝无效时间和不明确的目标身份。"""
        goals = tuple(self.focus_goal_ids)
        if len(set(goals)) != len(goals):
            raise ValueError("记忆读取的焦点目标不能重复")
        for goal in goals:
            if not Identifier.parse(goal).path.startswith("goal/"):
                raise ValueError("记忆焦点必须引用目标")
        if self.cursor is not None and self.cursor < 0:
            raise ValueError("记忆读取游标不能小于零")
        if self.max_characters <= 0:
            raise ValueError("记忆读取预算必须为正数")
        if self.observed_at is not None and (self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None):
            raise ValueError("记忆读取时间必须包含时区")
        if self.scopes is not None:
            scopes = frozenset(self.scopes)
            if any(not scope.strip() for scope in scopes):
                raise ValueError("记忆读取域不能为空")
            object.__setattr__(self, "scopes", scopes)
        object.__setattr__(self, "focus_goal_ids", goals)


@dataclass(frozen=True, slots=True)
class MemoryScore:
    """完整候选池中的一项评分，尚不表示进入上下文。"""

    memory_id: str
    score: float
    similarity: float = 0.0
    routes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """评分可稳定序列化，召回路线保持不可变。"""
        if not self.memory_id.strip() or not math.isfinite(self.score) or not 0 <= self.similarity <= 1:
            raise ValueError("记忆评分需要有效身份和有限数值")
        object.__setattr__(self, "routes", tuple(self.routes))


@dataclass(frozen=True, slots=True)
class MemoryRecall:
    """在固定知识截点上的实际读取条件、模型和完整排序结果。"""

    request: MemoryRequest
    policy: ResourceRef
    window_start: datetime
    commits_per_scope: int
    ranking: tuple[MemoryScore, ...] = ()
    parameters: Mapping[str, float | int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """不能把未冻结的读取或未确定的模型版本记作可追溯输入。"""
        if self.request.cursor is None or self.request.observed_at is None or self.request.scopes is None:
            raise ValueError("召回审计需要明确游标、时间与实际读取域")
        if self.policy.revision is None or self.commits_per_scope <= 0:
            raise ValueError("召回审计需要确定模型版本和有效候选限制")
        ranking = tuple(self.ranking)
        if len({item.memory_id for item in ranking}) != len(ranking):
            raise ValueError("召回评分身份不能重复")
        if any(not math.isfinite(value) for value in self.parameters.values()):
            raise ValueError("召回模型参数必须是有限数值")
        object.__setattr__(self, "ranking", ranking)
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True, slots=True)
class MemoryExposure:
    """一次模型请求中实际装配的记忆，与召回推荐分开记录。"""

    required_ids: tuple[str, ...] = ()
    recommended_ids: tuple[str, ...] = ()
    included_ids: tuple[str, ...] = ()
    missing_refs: tuple[str, ...] = ()
    focus_goal_ids: tuple[str, ...] = ()
    state_version: int | None = None
    recall: MemoryRecall | None = None

    def __post_init__(self) -> None:
        """实际载入必须来自完整证据或推荐集合，必要证据不能悄悄退出。"""
        for name in ("required_ids", "recommended_ids", "included_ids", "missing_refs", "focus_goal_ids"):
            object.__setattr__(self, name, tuple(dict.fromkeys(getattr(self, name))))
        included = set(self.included_ids)
        if not set(self.required_ids) <= included:
            raise ValueError("上下文曝光不能缺少必要证据")
        if not included <= set(self.required_ids) | set(self.recommended_ids):
            raise ValueError("上下文曝光含有未参与读取的记忆")
