"""规则与学习推荐器共享的排序效用评估。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.contracts.pkgs.memory import MemoryPolicy
    from src.memory_model.dataset import MemoryEpisode


def evaluate_policy(policy: MemoryPolicy, episodes: tuple[MemoryEpisode, ...], *, limit: int = 5) -> dict[str, float]:
    """比较推荐结果，收益来自独立标签，不把曝光或点击直接当作成功。"""
    examples = tuple(example for episode in episodes for example in episode.examples)
    if not examples or limit <= 0:
        raise ValueError("记忆评估需要样本和正数排序长度")
    accuracy = regret = ndcg = recall = 0.0
    for example in examples:
        scores = policy.score(example.request)
        if len(scores) != len(example.utilities) or any(not math.isfinite(score) for score in scores):
            raise ValueError("记忆策略没有返回有效完整评分")
        utilities = example.utilities
        ranked = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
        best = max(utilities)
        accuracy += utilities[ranked[0]] == best
        regret += best - utilities[ranked[0]]
        selected = ranked[:limit]
        ideal = sorted(utilities, reverse=True)[:limit]
        denominator = _dcg(ideal)
        ndcg += _dcg([utilities[index] for index in selected]) / denominator if denominator > 0 else 1.0
        positives = sum(value > 0 for value in utilities)
        recall += sum(utilities[index] > 0 for index in selected) / positives if positives else 1.0
    count = len(examples)
    return {"top1_accuracy": accuracy / count, "regret": regret / count, "ndcg": ndcg / count, "recall": recall / count}


def _dcg(utilities: list[float] | tuple[float, ...]) -> float:
    """使用非负线性收益，避免高数值标签指数溢出。"""
    return sum(max(0.0, value) / math.log2(index + 2) for index, value in enumerate(utilities))
