"""记忆召回和上下文曝光的版本化公开数据格式。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.contracts.memory import MemoryExposure, MemoryRecall, MemoryRequest, MemoryScore
from src.contracts.resource import ResourceKey, ResourceRef

if TYPE_CHECKING:
    from collections.abc import Mapping


def exposure_data(exposure: MemoryExposure) -> dict[str, Any]:
    """分别编码候选、推荐和实际载入，不把其中任何一项当作收益。"""
    return {
        "schema_version": 1,
        "required_ids": list(exposure.required_ids),
        "recommended_ids": list(exposure.recommended_ids),
        "included_ids": list(exposure.included_ids),
        "transcript_ids": list(exposure.transcript_ids),
        "missing_refs": list(exposure.missing_refs),
        "focus_goal_ids": list(exposure.focus_goal_ids),
        "state_version": exposure.state_version,
        "recall": recall_data(exposure.recall) if exposure.recall is not None else None,
    }


def recall_data(recall: MemoryRecall) -> dict[str, Any]:
    """实际域集合和模型参数属于输入事实，不能在回放时重新推导。"""
    request = recall.request
    return {
        "schema_version": 1,
        "query": request.query,
        "focus_goal_ids": list(request.focus_goal_ids),
        "scopes": sorted(request.scopes or ()),
        "cursor": request.cursor,
        "observed_at": request.observed_at.isoformat() if request.observed_at is not None else None,
        "max_characters": request.max_characters,
        "window_start": recall.window_start.isoformat(),
        "commits_per_scope": recall.commits_per_scope,
        "policy": {"key": str(recall.policy.key), "revision": recall.policy.revision},
        "parameters": dict(recall.parameters),
        "ranking": [
            {
                "memory_id": item.memory_id,
                "score": item.score,
                "similarity": item.similarity,
                "routes": list(item.routes),
            }
            for item in recall.ranking
        ],
    }


def read_exposure(data: Mapping[str, Any]) -> MemoryExposure:
    """只接受已声明的格式，缺失来源不能伪装成可重放读取。"""
    if data["schema_version"] != 1:
        raise ValueError("不支持的记忆曝光格式")
    return MemoryExposure(
        tuple(data["required_ids"]),
        tuple(data["recommended_ids"]),
        tuple(data["included_ids"]),
        tuple(data["missing_refs"]),
        tuple(data["focus_goal_ids"]),
        data["state_version"],
        read_recall(data["recall"]) if data["recall"] is not None else None,
        tuple(data.get("transcript_ids", ())),
    )


def read_recall(data: Mapping[str, Any]) -> MemoryRecall:
    """恢复确定的知识前缀和候选评分，不加载模型或访问世界。"""
    if data["schema_version"] != 1:
        raise ValueError("不支持的记忆召回格式")
    request = MemoryRequest(
        data["query"],
        tuple(data["focus_goal_ids"]),
        frozenset(data["scopes"]),
        data["cursor"],
        datetime.fromisoformat(data["observed_at"]),
        data["max_characters"],
    )
    policy = ResourceRef(ResourceKey.parse(data["policy"]["key"]), data["policy"]["revision"])
    ranking = tuple(
        MemoryScore(item["memory_id"], item["score"], item["similarity"], tuple(item["routes"]))
        for item in data["ranking"]
    )
    return MemoryRecall(
        request,
        policy,
        datetime.fromisoformat(data["window_start"]),
        data["commits_per_scope"],
        ranking,
        data["parameters"],
    )
