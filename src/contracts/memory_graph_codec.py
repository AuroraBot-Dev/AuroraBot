"""在线排序与离线训练共享的记忆图输入格式和内容指纹。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.contracts.memory_graph import MemoryCandidate, MemoryInteraction, MemoryNode, MemoryRankingRequest

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


def ranking_data(request: MemoryRankingRequest) -> dict[str, Any]:
    """只导出读取当时的输入，监督效用不属于此格式。"""
    return {
        "query": request.query,
        "focus_goal_ids": list(request.focus_goal_ids),
        "cursor": request.cursor,
        "observed_at": request.observed_at.isoformat(),
        "candidates": [
            {
                "memory_id": item.memory_id,
                "text": item.text,
                "cursor": item.cursor,
                "occurred_at": item.occurred_at.isoformat(),
                "recorded_at": item.recorded_at.isoformat(),
                "similarity": item.similarity,
                "goal_match": item.goal_match,
                "entity_match": item.entity_match,
            }
            for item in request.candidates
        ],
        "interactions": [
            {
                "cursor": item.cursor,
                "recorded_at": item.recorded_at.isoformat(),
                "source": {"kind": item.source.kind, "identity": item.source.identity, "text": item.source.text},
                "target": {"kind": item.target.kind, "identity": item.target.identity, "text": item.target.text},
                "relation": item.relation,
                "value": item.value,
            }
            for item in request.interactions
        ],
    }


def ranking_fingerprint(request: MemoryRankingRequest) -> str:
    """指纹绑定确切候选、图前缀、特征和时间坐标。"""
    content = json.dumps(ranking_data(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def interactions_fingerprint(events: Iterable[MemoryInteraction]) -> str:
    """逐条绑定交互内容和次序，不把候选或当前问题混入图状态身份。"""
    digest = hashlib.sha256(b"aurora:memory/graph-prefix@1\n")
    for event in events:
        data = {
            "cursor": event.cursor,
            "recorded_at": event.recorded_at.astimezone(UTC).isoformat(),
            "source": (event.source.kind, event.source.identity, event.source.text),
            "target": (event.target.kind, event.target.identity, event.target.text),
            "relation": event.relation,
            "value": float(event.value),
        }
        digest.update(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def read_ranking(data: Mapping[str, Any]) -> MemoryRankingRequest:
    """离线和重放读取同一输入，不允许未来交互混入查询前缀。"""
    candidates = tuple(
        MemoryCandidate(
            item["memory_id"],
            item["text"],
            item["cursor"],
            datetime.fromisoformat(item["occurred_at"]),
            datetime.fromisoformat(item["recorded_at"]),
            item.get("similarity", 0),
            item.get("goal_match", False),
            item.get("entity_match", False),
        )
        for item in data["candidates"]
    )
    events = tuple(
        MemoryInteraction(
            item["cursor"],
            datetime.fromisoformat(item["recorded_at"]),
            MemoryNode(**item["source"]),
            MemoryNode(**item["target"]),
            item["relation"],
            item.get("value", 1.0),
        )
        for item in data.get("interactions", ())
    )
    return MemoryRankingRequest(
        data["query"],
        tuple(data["focus_goal_ids"]),
        data["cursor"],
        datetime.fromisoformat(data["observed_at"]),
        candidates,
        events,
    )
