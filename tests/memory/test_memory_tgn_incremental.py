"""增量图状态与完整重放等价，历史和并发查询不能共享错误前缀。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import torch

from aurorabot.memory_model.tgn import TemporalMemoryNetwork, TGNMemoryPolicy
from tests.memory.tgn_support import _cold, _network, _request

if TYPE_CHECKING:
    from aurorabot.contracts.memory_graph import MemoryInteraction
    from aurorabot.memory_model.tgn import GraphState


def test_unchanged_prefix_only_applies_new_interactions(monkeypatch: pytest.MonkeyPatch) -> None:
    """相同历史换问题和候选仍需重新评分，却不应重做历史节点更新。"""
    network = _network()
    full = _request(True)
    prefix = replace(full, cursor=2, interactions=full.interactions[:-1])
    changed = replace(
        full,
        query="重新评估另一目标",
        focus_goal_ids=("aurora:goal/other",),
        observed_at=full.observed_at + timedelta(hours=1),
        candidates=full.candidates[::-1],
    )
    expected = tuple(_cold(network, request) for request in (prefix, full, changed))
    updates: list[MemoryInteraction] = []
    actual_update = TemporalMemoryNetwork.update

    def update(self: TemporalMemoryNetwork, state: GraphState, event: MemoryInteraction) -> None:
        """观察实际 GRU 消息更新，计算过程保持不变。"""
        updates.append(event)
        actual_update(self, state, event)

    monkeypatch.setattr(TemporalMemoryNetwork, "update", update)
    policy = TGNMemoryPolicy(network, "controlled")
    assert policy.score(prefix) == expected[0]
    assert updates == list(prefix.interactions)
    updates.clear()
    assert policy.score(full) == expected[1]
    assert updates == list(full.interactions[len(prefix.interactions) :])
    updates.clear()
    assert policy.score(changed) == expected[2]
    assert policy.score(full) == expected[1]
    assert not updates


def test_historical_and_filtered_graphs_do_not_reuse_future_or_excluded_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    """相同游标不足以识别同一图，边、文本和读取范围都必须参与前缀核对。"""
    network = _network()
    full = _request(True)
    historical = replace(full, cursor=2, interactions=full.interactions[:-1])
    filtered = replace(full, interactions=tuple(item for item in full.interactions if item.relation != "scope"))
    edited = replace(
        full,
        interactions=(
            replace(full.interactions[0], source=replace(full.interactions[0].source, text="不同的原始内容")),
            *full.interactions[1:],
        ),
    )
    branch = _request(False)
    requests = (full, historical, filtered, edited, branch, replace(full, interactions=()))
    expected = tuple(_cold(network, request) for request in requests)
    policy = TGNMemoryPolicy(network, "controlled")
    assert policy.score(full) == expected[0]
    for request, reference in zip(requests[1:], expected[1:], strict=True):
        assert policy.score(request) == reference

    def unexpected_update(self: TemporalMemoryNetwork, state: GraphState, event: MemoryInteraction) -> None:
        """临时历史和等长分支完成后，原主前缀应仍可直接复用。"""
        raise AssertionError("不应再次重放已确认的主图前缀")

    monkeypatch.setattr(TemporalMemoryNetwork, "update", unexpected_update)
    assert policy.score(full) == expected[0]


def test_longer_divergent_history_becomes_its_own_valid_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """更长的新分支先完整构建，后续同分支复用不能混入原分支的反馈。"""
    network = _network()
    full, branch = _request(True), _request(False)
    extra = replace(
        branch.interactions[-1], cursor=4, recorded_at=branch.observed_at + timedelta(seconds=1), value=-1.0
    )
    longer = replace(branch, cursor=4, observed_at=extra.recorded_at, interactions=(*branch.interactions, extra))
    expected = _cold(network, full), _cold(network, longer)
    policy = TGNMemoryPolicy(network, "controlled")
    assert policy.score(full) == expected[0]
    assert policy.score(longer) == expected[1]

    def unexpected_update(self: TemporalMemoryNetwork, state: GraphState, event: MemoryInteraction) -> None:
        """已经独立确认的新前缀也应能够复用。"""
        raise AssertionError("不应重放新分支的相同前缀")

    with monkeypatch.context() as patch:
        patch.setattr(TemporalMemoryNetwork, "update", unexpected_update)
        assert policy.score(longer) == expected[1]
    assert policy.score(full) == expected[0]


def test_projection_failure_discards_partial_state_before_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """在追加消息已经改变节点后中断，重试也不能把该消息作用两遍。"""
    network = _network()
    full = _request(True)
    prefix = replace(full, cursor=2, interactions=full.interactions[:-1])
    expected = _cold(network, full)
    policy = TGNMemoryPolicy(network, "controlled")
    policy.score(prefix)
    actual_update = TemporalMemoryNetwork.update
    should_fail = True

    def update_then_fail(self: TemporalMemoryNetwork, state: GraphState, event: MemoryInteraction) -> None:
        """先执行真实更新，再模拟工作线程计算失败。"""
        nonlocal should_fail
        actual_update(self, state, event)
        if event == full.interactions[-1] and should_fail:
            should_fail = False
            raise RuntimeError("消息更新中断")

    monkeypatch.setattr(TemporalMemoryNetwork, "update", update_then_fail)
    with pytest.raises(RuntimeError, match="消息更新中断"):
        policy.score(full)
    assert policy.score(full) == expected
    assert policy.score(full) == expected


def test_concurrent_different_queries_match_independent_full_replays() -> None:
    """多个线程交错读取当前、历史和另一分支时，每份结果仍对应自己的图。"""
    network = _network()
    full = _request(True)
    prefix = replace(full, cursor=2, interactions=full.interactions[:-1])
    requests = (full, prefix, _request(False), replace(full, candidates=full.candidates[::-1]), full) * 3
    expected = tuple(_cold(network, request) for request in requests)
    policy = TGNMemoryPolicy(network, "controlled")
    with ThreadPoolExecutor(max_workers=3) as workers:
        actual = tuple(workers.map(policy.score, requests))
    assert actual == expected


def test_policy_owns_fixed_weights_separate_from_the_training_network() -> None:
    """外部继续训练原网络时，已登记版本的在线策略不能悄悄改变参数。"""
    network = _network()
    full, branch = _request(True), _request(False)
    expected = _cold(network, full), _cold(network, branch)
    policy = TGNMemoryPolicy(network, "controlled")
    assert policy.score(full) == expected[0]
    with torch.no_grad():
        for parameter in network.parameters():
            parameter.add_(1.0)
    assert policy.score(branch) == expected[1]
    assert policy.score(full) == expected[0]
