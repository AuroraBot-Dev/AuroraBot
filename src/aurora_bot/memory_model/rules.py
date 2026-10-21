"""记忆相关性、任务关系和时效性的固定排序基线。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from aurora_bot.contracts.resource import ResourceKey, ResourceRef

if TYPE_CHECKING:
    from aurora_bot.contracts.memory_graph import MemoryRankingRequest


class RuleMemoryPolicy:
    """简单可复现的比较基准，不从过去曝光推断正确效用。"""

    @property
    def ref(self) -> ResourceRef:
        """为这套固定评分语义提供确定版本。"""
        return ResourceRef(ResourceKey.parse("aurora:memory/model/rules"), "1")

    @property
    def parameters(self) -> dict[str, float | int]:
        """固定权重同样公开，便于比较和追溯。"""
        return {"similarity": 4, "goal_match": 2, "entity_match": 1, "recency_seconds": 3600}

    def score(self, request: MemoryRankingRequest) -> tuple[float, ...]:
        """只使用当前候选的可见特征。"""
        return tuple(
            4 * item.similarity
            + 2 * item.goal_match
            + item.entity_match
            + math.exp(-max(0.0, (request.observed_at - item.occurred_at).total_seconds()) / 3600)
            for item in request.candidates
        )
