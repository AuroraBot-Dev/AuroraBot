"""在线策略恢复前缀后仍需由实际查询确认，未来状态不能穿越读取边界。"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from test_memory_tgn import _request
from test_memory_tgn_incremental import _cold, _network

from src.contracts.memory_graph_codec import interactions_fingerprint
from src.memory_model.tgn import TemporalMemoryNetwork, TGNMemoryPolicy

if TYPE_CHECKING:
    from src.contracts.memory_graph import MemoryInteraction
    from src.memory_model.state import GraphState


def test_restored_prefix_only_updates_the_remaining_real_interactions(monkeypatch: pytest.MonkeyPatch) -> None:
    """保存后重建策略，已确认节点无需重放，反馈追加仍与完整计算一致。"""
    full = _request(True)
    prefix = replace(full, cursor=2, interactions=full.interactions[:-1])
    network = _network()
    source = TGNMemoryPolicy(network, "same-weights")
    source.score(prefix)
    checkpoint = source.checkpoint()
    assert checkpoint is not None
    assert checkpoint.prefix.digest == interactions_fingerprint(prefix.interactions)
    assert source.checkpoint(after=checkpoint.prefix.digest) is None
    expected = _cold(network, full)
    restored = TGNMemoryPolicy(network, "same-weights")
    assert restored.restore(checkpoint)
    assert restored.checkpoint() is None
    updates: list[MemoryInteraction] = []
    actual_update = TemporalMemoryNetwork.update

    def update(self: TemporalMemoryNetwork, state: GraphState, event: MemoryInteraction) -> None:
        """保留真实节点计算，核对恢复后实际处理的消息。"""
        updates.append(event)
        actual_update(self, state, event)

    monkeypatch.setattr(TemporalMemoryNetwork, "update", update)
    assert restored.score(full) == expected
    assert updates == list(full.interactions[len(prefix.interactions) :])
    newer = restored.checkpoint(after=checkpoint.prefix.digest)
    assert newer is not None
    assert newer.prefix.digest == interactions_fingerprint(full.interactions)


@pytest.mark.parametrize("reading", ["historical", "filtered", "branch", "empty"])
def test_first_query_must_not_use_restored_future_or_different_history(reading: str) -> None:
    """恢复记录本身不足以确认当前可见历史，范围和交互均由真实输入决定。"""
    full = _request(True)
    request = full
    if reading == "historical":
        request = replace(full, cursor=2, interactions=full.interactions[:-1])
    elif reading == "filtered":
        request = replace(full, interactions=tuple(event for event in full.interactions if event.relation != "scope"))
    elif reading == "branch":
        request = _request(False)
    else:
        request = replace(full, interactions=())
    network = _network()
    source = TGNMemoryPolicy(network, "same-weights")
    source.score(full)
    checkpoint = source.checkpoint()
    assert checkpoint is not None
    restored = TGNMemoryPolicy(network, "same-weights")
    assert restored.restore(checkpoint)
    assert restored.score(request) == _cold(network, request)
    current = restored.checkpoint()
    if request.interactions:
        assert current is not None
        assert current.prefix.digest == interactions_fingerprint(request.interactions)
    else:
        assert current is None
    assert restored.score(full) == _cold(network, full)


def test_incompatible_or_damaged_checkpoint_does_not_replace_live_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    """旧模型检查点和坏文件均不能清除已经确认的当前图状态。"""
    request = _request(True)
    policy = TGNMemoryPolicy(_network(), "current-weights")
    expected = policy.score(request)
    checkpoint = policy.checkpoint()
    assert checkpoint is not None
    other = replace(checkpoint, model=replace(checkpoint.model, revision="other-weights"))
    assert not policy.restore(other)
    with pytest.raises(ValueError, match="检查点已损坏"):
        policy.restore(replace(checkpoint, content=b"broken snapshot"))

    def unexpected_update(self: TemporalMemoryNetwork, state: GraphState, event: MemoryInteraction) -> None:
        """无效恢复之后，当前前缀仍应保持可复用。"""
        raise AssertionError("有效的当前状态不应被替换")

    monkeypatch.setattr(TemporalMemoryNetwork, "update", unexpected_update)
    assert policy.score(request) == expected
