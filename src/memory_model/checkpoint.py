"""动态节点检查点只保存张量和基本类型，并验证完整图边界。"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pickle import UnpicklingError
from typing import TYPE_CHECKING, Any
from zipfile import is_zipfile

import torch
from torch import Tensor

from src.contracts.memory_checkpoint import MemoryGraphPrefix, MemoryPolicyCheckpoint
from src.contracts.memory_checkpoint_codec import prefix_data
from src.contracts.memory_graph import MEMORY_NODE_KINDS, MEMORY_RELATIONS, MemoryNode
from src.memory_model.coordinates import TIME_SCALE
from src.memory_model.state import GraphState
from src.utils.features import TEXT_FEATURE_SCHEMA

if TYPE_CHECKING:
    from src.contracts.resource import ResourceRef

_SCHEMA_VERSION = 1
_NODE_KEY_PARTS = 2


def encode_state(
    state: GraphState, model: ResourceRef, prefix: MemoryGraphPrefix, *, hidden_size: int, text_dimensions: int
) -> MemoryPolicyCheckpoint:
    """保存节点、邻居和隐状态，不保存权重、梯度或查询特征缓存。"""
    keys = sorted(state.nodes)
    data = {
        "schema_version": _SCHEMA_VERSION,
        "model": {"key": str(model.key), "revision": model.revision},
        "prefix": prefix_data(prefix),
        "coordinates": _coordinates(hidden_size, text_dimensions),
        "nodes": [
            {
                "kind": state.nodes[key].kind,
                "identity": state.nodes[key].identity,
                "text": state.nodes[key].text,
                "updated_at": state.updated_at[key].astimezone(UTC).isoformat(),
                "neighbors": sorted(state.neighbors.get(key, ())),
            }
            for key in keys
        ],
        "memories": torch.stack([state.memories[key].detach().cpu() for key in keys]),
    }
    stream = BytesIO()
    torch.save(data, stream)
    return MemoryPolicyCheckpoint(model, prefix, stream.getvalue())


def decode_state(
    checkpoint: MemoryPolicyCheckpoint, model: ResourceRef, *, hidden_size: int, text_dimensions: int
) -> GraphState | None:
    """版本不兼容时重建，损坏正文则明确拒绝，不交付部分节点状态。"""
    if checkpoint.model != model:
        return None
    try:
        stream = BytesIO(checkpoint.content)
        if not is_zipfile(stream):
            raise ValueError("检查点必须使用完整的张量归档")
        stream.seek(0)
        data = torch.load(stream, map_location="cpu", weights_only=True)
        if not isinstance(data, dict):
            raise ValueError("检查点顶层必须是对象")
        if data["schema_version"] != _SCHEMA_VERSION or data["coordinates"] != _coordinates(
            hidden_size, text_dimensions
        ):
            return None
        if data["model"] != {"key": str(model.key), "revision": model.revision}:
            raise ValueError("检查点正文的模型身份不一致")
        if data["prefix"] != prefix_data(checkpoint.prefix):
            raise ValueError("检查点正文的历史边界不一致")
        return _read_nodes(data["nodes"], data["memories"], checkpoint.prefix, hidden_size)
    except (ValueError, TypeError, LookupError, RuntimeError, EOFError, OSError, UnpicklingError) as error:
        raise ValueError("时序记忆检查点已损坏，不能恢复节点状态") from error


def _coordinates(hidden_size: int, text_dimensions: int) -> dict[str, Any]:
    """计算语义变化后，动态状态必须重新投影。"""
    return {
        "projection_schema": "aurora:memory/projection/tgn@1",
        "framework": str(torch.__version__),
        "device": "cpu",
        "dtype": "float32",
        "hidden_size": hidden_size,
        "text_dimensions": text_dimensions,
        "node_kinds": list(MEMORY_NODE_KINDS),
        "relations": list(MEMORY_RELATIONS),
        "text_features": TEXT_FEATURE_SCHEMA,
        "time_scale": TIME_SCALE,
    }


def _read_nodes(
    rows: list[dict[str, Any]], memories: Tensor, prefix: MemoryGraphPrefix, hidden_size: int
) -> GraphState:
    """张量形状、节点身份、获知时间和双向邻接必须一起有效。"""
    if not isinstance(rows, list) or not rows or not isinstance(memories, Tensor):
        raise ValueError("检查点缺少节点和张量")
    if memories.dtype != torch.float32 or tuple(memories.shape) != (len(rows), hidden_size):
        raise ValueError("节点张量的形状或类型不匹配")
    if not bool(torch.isfinite(memories).all()):
        raise ValueError("节点张量包含非有限数值")
    state = GraphState()
    for row, memory in zip(rows, memories, strict=True):
        if not isinstance(row, dict) or any(not isinstance(row.get(key), str) for key in ("kind", "identity", "text")):
            raise ValueError("节点身份必须是文本")
        node = MemoryNode(row["kind"], row["identity"], row["text"])
        updated = datetime.fromisoformat(row["updated_at"])
        if (
            node.key in state.nodes
            or updated.tzinfo is None
            or updated.utcoffset() is None
            or updated > prefix.recorded_at
        ):
            raise ValueError("节点身份重复或更新时间越过历史边界")
        neighbors = row["neighbors"]
        if not isinstance(neighbors, list) or any(
            not isinstance(key, (list, tuple))
            or len(key) != _NODE_KEY_PARTS
            or any(not isinstance(part, str) for part in key)
            for key in neighbors
        ):
            raise ValueError("邻居身份无效")
        state.nodes[node.key] = node
        state.memories[node.key] = memory.clone()
        state.updated_at[node.key] = updated.astimezone(UTC)
        state.neighbors[node.key] = {(key[0], key[1]) for key in neighbors}
    for key, neighbors in state.neighbors.items():
        if key in neighbors or any(
            other not in state.nodes or key not in state.neighbors[other] for other in neighbors
        ):
            raise ValueError("节点邻接关系不完整")
    return state
