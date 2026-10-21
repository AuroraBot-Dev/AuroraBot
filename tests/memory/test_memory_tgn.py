"""时序记忆网络保留真实循环与邻域信息，复用状态必须匹配确切历史。"""

from __future__ import annotations

from dataclasses import replace

import torch

from aurora_bot.memory_model.tgn import TemporalMemoryNetwork, TGNMemoryPolicy
from tests.memory.tgn_support import _request


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
