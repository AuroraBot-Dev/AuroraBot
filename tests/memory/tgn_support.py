"""复用的离线场景构造与替身，不依赖测试用例模块。"""

from __future__ import annotations

import torch

from aurora_bot.contracts.memory_graph import MemoryCandidate, MemoryInteraction, MemoryNode, MemoryRankingRequest
from aurora_bot.memory.graph import graph_interactions
from aurora_bot.memory_model.tgn import TemporalMemoryNetwork
from tests.memory.facts import _NOW, _fact


def _request(helpful: bool) -> MemoryRankingRequest:
    """当前查询和候选完全相同，只改变此前已知的采用结果。"""
    first = _fact("first", "实验记录", 1, goal_ids=["aurora:goal/check"])
    second = _fact("second", "实验记录", 2, goal_ids=["aurora:goal/check"])
    events = graph_interactions((first, second))
    feedback = MemoryInteraction(
        3,
        _NOW,
        MemoryNode("goal", "aurora:goal/check", "aurora:goal/check"),
        MemoryNode("memory", first.commit_id, first.summary),
        "useful" if helpful else "unhelpful",
    )
    candidates = tuple(
        MemoryCandidate(commit.commit_id, commit.summary, commit.cursor, commit.occurred_at, _NOW, 1.0, True)
        for commit in (first, second)
    )
    return MemoryRankingRequest("继续实验", ("aurora:goal/check",), 3, _NOW, candidates, (*events, feedback))


def _network() -> TemporalMemoryNetwork:
    """固定参数便于比较缓存和完整重放，不改变其他测试的随机状态。"""
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(11)
        return TemporalMemoryNetwork(8, 16).eval()


def _cold(network: TemporalMemoryNetwork, request: MemoryRankingRequest) -> tuple[float, ...]:
    """直接执行训练所用的完整图路径，作为独立等价性参考。"""
    with torch.no_grad():
        return tuple(network(request).tolist())
