"""动态图检查点与完整重放等价，正文和历史边界均需有效。"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta, timezone
from io import BytesIO
from typing import Any

import pytest
import torch
from test_memory_tgn import _request
from test_memory_tgn_incremental import _network

from src.contracts.memory_checkpoint import MemoryGraphPrefix, MemoryPolicyCheckpoint
from src.contracts.memory_graph_codec import interactions_fingerprint
from src.contracts.resource import ResourceRef
from src.memory_model.checkpoint import decode_state, encode_state
from src.memory_model.coordinates import TGN_KEY

_MODEL = ResourceRef(TGN_KEY, "controlled")
_DIMENSIONS = {"hidden_size": 8, "text_dimensions": 16}


def _checkpoint() -> MemoryPolicyCheckpoint:
    """保存反馈发生之前的真实图投影，供后续增量恢复。"""
    request = _request(True)
    events = request.interactions[:-1]
    prefix = MemoryGraphPrefix(len(events), events[-1].cursor, events[-1].recorded_at, interactions_fingerprint(events))
    with torch.no_grad():
        state = _network().project(events)
        return encode_state(state, _MODEL, prefix, **_DIMENSIONS)


def _replace_data(checkpoint: MemoryPolicyCheckpoint, data: dict[str, Any]) -> MemoryPolicyCheckpoint:
    """以安全基础类型构造损坏样本，不保存可执行对象。"""
    stream = BytesIO()
    torch.save(data, stream)
    return replace(checkpoint, content=stream.getvalue())


def test_restored_nodes_continue_to_the_same_scores_as_full_replay() -> None:
    """恢复的是独立节点张量，后续反馈仍通过真实 GRU 和邻域评分。"""
    checkpoint = _checkpoint()
    state = decode_state(checkpoint, _MODEL, **_DIMENSIONS)
    assert state is not None
    assert not state.features
    request = _request(True)
    network = _network()
    with torch.no_grad():
        network.project(request.interactions[checkpoint.prefix.count :], state)
        assert torch.equal(network.rank(request, state), network(request))
    data = torch.load(BytesIO(checkpoint.content), weights_only=True)
    assert "state_dict" not in data
    assert "features" not in data


def test_model_or_coordinate_mismatch_requires_a_fresh_projection() -> None:
    """换权重或编码维度时不能继续使用旧动态状态。"""
    checkpoint = _checkpoint()
    assert decode_state(checkpoint, ResourceRef(TGN_KEY, "other"), **_DIMENSIONS) is None
    assert decode_state(checkpoint, _MODEL, hidden_size=16, text_dimensions=16) is None
    data = torch.load(BytesIO(checkpoint.content), weights_only=True)
    data["coordinates"]["relations"].reverse()
    assert decode_state(_replace_data(checkpoint, data), _MODEL, **_DIMENSIONS) is None


@pytest.mark.parametrize("coordinate", ["framework", "device", "dtype", "projection_schema"])
def test_computation_runtime_changes_invalidate_the_old_projection(coordinate: str) -> None:
    """相同权重也不能把不同执行坐标产生的节点状态混入当前推理。"""
    checkpoint = _checkpoint()
    data = torch.load(BytesIO(checkpoint.content), weights_only=True)
    data["coordinates"][coordinate] = "other"
    assert decode_state(_replace_data(checkpoint, data), _MODEL, **_DIMENSIONS) is None


@pytest.mark.parametrize("damage", ["nan", "shape", "dtype", "duplicate", "neighbor", "future", "boundary"])
def test_invalid_node_payload_is_rejected_as_a_whole(damage: str) -> None:
    """部分有效的节点不能掩盖损坏张量、断边或未来更新时间。"""
    checkpoint = _checkpoint()
    data = torch.load(BytesIO(checkpoint.content), weights_only=True)
    if damage == "nan":
        data["memories"][0, 0] = float("nan")
    elif damage == "shape":
        data["memories"] = data["memories"][:, :-1]
    elif damage == "dtype":
        data["memories"] = data["memories"].double()
    elif damage == "duplicate":
        data["nodes"][1] = data["nodes"][0]
    elif damage == "neighbor":
        data["nodes"][0]["neighbors"] = [("memory", "missing")]
    elif damage == "future":
        data["nodes"][0]["updated_at"] = (checkpoint.prefix.recorded_at + timedelta(seconds=1)).isoformat()
    else:
        data["prefix"]["digest"] = "a" * 64
    with pytest.raises(ValueError, match="检查点已损坏"):
        decode_state(_replace_data(checkpoint, data), _MODEL, **_DIMENSIONS)


def test_unreadable_bytes_and_mismatched_outer_boundary_are_rejected() -> None:
    """外层描述不能把相同字节冒充为另一段历史的投影。"""
    checkpoint = _checkpoint()
    for altered in (
        replace(checkpoint, content=b"not a tensor checkpoint"),
        replace(checkpoint, prefix=replace(checkpoint.prefix, digest="b" * 64)),
    ):
        with pytest.raises(ValueError, match="检查点已损坏"):
            decode_state(altered, _MODEL, **_DIMENSIONS)


def test_graph_fingerprint_binds_all_interactions_without_timezone_representation_noise() -> None:
    """同一瞬间的时区表示等价，交互内容、顺序或数量变化则失配。"""
    events = _request(True).interactions
    digest = interactions_fingerprint(events)
    shifted = tuple(
        replace(event, recorded_at=event.recorded_at.astimezone(timezone(timedelta(hours=8)))) for event in events
    )
    assert interactions_fingerprint(iter(shifted)) == digest
    assert interactions_fingerprint(events[:-1]) != digest
    assert interactions_fingerprint(events[::-1]) != digest
    assert interactions_fingerprint((*events[:-1], replace(events[-1], value=2.0))) != digest
