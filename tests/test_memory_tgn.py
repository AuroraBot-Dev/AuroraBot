"""时序记忆网络保留真实循环与邻域信息，复用状态必须匹配确切历史。"""

from __future__ import annotations

from dataclasses import replace

import torch

from aurorabot.contracts.memory_graph import MemoryCandidate, MemoryInteraction, MemoryNode, MemoryRankingRequest
from aurorabot.memory.graph import graph_interactions
from aurorabot.memory_model.tgn import TemporalMemoryNetwork, TGNMemoryPolicy
from tests.test_memory_selection import _NOW, _fact


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


def test_temporal_graph_history_changes_scores_and_receives_gradients() -> None:
    """改变历史反馈影响相同当前输入，梯度确实经过消息、循环和邻域编码。"""
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(7)
        network = TemporalMemoryNetwork(hidden_size=8, text_dimensions=16)
        useful, harmful = _request(True), _request(False)
        assert useful.candidates == harmful.candidates
        assert useful.query == harmful.query
        positive = network(useful)
        negative = network(harmful)
        assert not torch.allclose(positive, negative)
        positive.sum().backward()
        parameters = dict(network.named_parameters())
        for name in ("recurrent.weight_hh", "message.0.weight", "embedding.0.weight", "relation_encoder.weight"):
            gradient = parameters[name].grad
            assert gradient is not None
            assert bool(torch.isfinite(gradient).all())
            assert float(gradient.abs().sum()) > 0


def test_policy_isolates_history_branches_and_handles_empty_candidate_set() -> None:
    """实时读取另一个历史后，重放原查询仍获得相同分数。"""
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(3)
        policy = TGNMemoryPolicy(TemporalMemoryNetwork(8, 16), "controlled")
        request = _request(True)
        first = policy.score(request)
        policy.score(_request(False))
        assert policy.score(request) == first
        assert policy.score(replace(request, candidates=())) == ()
