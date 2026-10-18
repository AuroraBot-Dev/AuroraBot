"""多路候选召回与有依赖的集合组装，完整原始提交始终保留来源。"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.contracts.memory import MemoryBundle
from src.utils.features import text_similarity

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from typing import Any

    from src.contracts.memory import MemoryContinuity, MemoryRequest
    from src.contracts.world import WorldCommit

_CANDIDATES_PER_ROUTE = 32


@dataclass(frozen=True, slots=True)
class MemorySelection:
    """区分恢复所需证据、可选记忆集合与无法取得的引用。"""

    required: tuple[WorldCommit, ...]
    bundles: tuple[MemoryBundle, ...]
    missing_refs: tuple[str, ...]


def select_memories(
    history: tuple[WorldCommit, ...],
    recent: tuple[WorldCommit, ...],
    request: MemoryRequest,
    continuity: MemoryContinuity | None,
    observed_at: datetime,
) -> MemorySelection:
    """从近期、文本、目标和实体四路召回，再整体补全证据依赖。"""
    records = {commit.commit_id: commit for commit in history}
    routes, similarities = _candidate_routes(history, recent, request, continuity)
    replacements: dict[str, list[str]] = defaultdict(list)
    for commit in history:
        for old in memory_links(commit, "supersedes"):
            replacements[old].append(commit.commit_id)
    required_refs = (
        tuple(ref for goal in continuity.goals for ref in goal.checkpoint.evidence_refs) if continuity else ()
    )
    required, missing = _closure(required_refs, records, replacements)
    required_ids = {commit.commit_id for commit in required}
    included = {commit.commit_id for commit in required}
    routes = {key: reasons for key, reasons in routes.items() if key not in replacements or key in required_refs}
    ranked = _rank_candidates(records, routes, similarities, observed_at)
    budget = request.max_characters
    bundles: list[MemoryBundle] = []
    for score, identity in ranked:
        if identity in included:
            continue
        complete, absent = _closure((identity,), records, replacements)
        if absent:
            continue
        commits = tuple(commit for commit in complete if commit.commit_id not in required_ids)
        size = sum(len(memory_text(commit)) + len(commit.commit_id) + 240 for commit in commits)
        if size > budget:
            continue
        bundles.append(MemoryBundle(commits, score, tuple(sorted(routes[identity]))))
        included.update(commit.commit_id for commit in commits)
        budget -= size
    return MemorySelection(required, tuple(bundles), missing)


def memory_text(commit: WorldCommit) -> str:
    """保留可读内容和完整结构化事实，用作基线特征及容量估算。"""
    return f"{commit.summary}\n{json.dumps(dict(commit.data), ensure_ascii=False, separators=(',', ':'))}"


def memory_links(commit: WorldCommit, name: str) -> tuple[str, ...]:
    """只读取显式关系元数据，格式错误的外部内容不产生图关系。"""
    metadata = commit.data.get("memory")
    links = _strings(metadata, name) if isinstance(metadata, dict) else ()
    if name == "goal_ids":
        direct = commit.data.get("goal_id")
        links += (direct,) if isinstance(direct, str) and direct.strip() else ()
        links += _strings(commit.data, "focus_goal_ids")
    return tuple(dict.fromkeys(links))


def _strings(data: Mapping[str, Any], name: str) -> tuple[str, ...]:
    """接受显式字符串集合，不把任意嵌套文本当成结构化关系。"""
    values = data.get(name, ())
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        return ()
    return tuple(values)


def _closure(
    identities: tuple[str, ...], records: Mapping[str, WorldCommit], replacements: Mapping[str, list[str]]
) -> tuple[tuple[WorldCommit, ...], tuple[str, ...]]:
    """按获知顺序保留前提与修订，环和共享依赖只展开一次。"""
    visited: set[str] = set()
    missing: set[str] = set()
    pending = list(identities)
    selected: list[WorldCommit] = []
    while pending:
        identity = pending.pop()
        if identity in visited:
            continue
        visited.add(identity)
        commit = records.get(identity)
        if commit is None:
            missing.add(identity)
            continue
        selected.append(commit)
        pending.extend(memory_links(commit, "depends_on"))
        pending.extend(replacements.get(identity, ()))
    return tuple(sorted(selected, key=lambda commit: commit.cursor)), tuple(sorted(missing))


def _candidate_routes(
    history: tuple[WorldCommit, ...],
    recent: tuple[WorldCommit, ...],
    request: MemoryRequest,
    continuity: MemoryContinuity | None,
) -> tuple[dict[str, set[str]], dict[str, float]]:
    """各条召回路线保留独立原因，学习排序可以替换其后续评分。"""
    routes: dict[str, set[str]] = defaultdict(set)
    for commit in recent:
        routes[commit.commit_id].add("recent")
    goals = set(request.focus_goal_ids)
    if continuity is not None:
        goals.update(goal.goal_id for goal in continuity.goals)
    similarities = {commit.commit_id: text_similarity(request.query, memory_text(commit)) for commit in history}
    lexical = sorted(history, key=lambda commit: (-similarities[commit.commit_id], -commit.cursor))
    for commit in lexical[:_CANDIDATES_PER_ROUTE]:
        if similarities[commit.commit_id] > 0:
            routes[commit.commit_id].add("text")
    for commit in reversed(history):
        if goals.intersection(memory_links(commit, "goal_ids")):
            routes[commit.commit_id].add("goal")
        if any(entity.casefold() in request.query.casefold() for entity in memory_links(commit, "entity_ids")):
            routes[commit.commit_id].add("entity")
    return routes, similarities


def _rank_candidates(
    records: Mapping[str, WorldCommit],
    routes: Mapping[str, set[str]],
    similarities: Mapping[str, float],
    observed_at: datetime,
) -> list[tuple[float, str]]:
    """使用可比较的固定相关性、任务关联和时效性基线。"""
    ranked: list[tuple[float, str]] = []
    for identity, reasons in routes.items():
        commit = records[identity]
        age = max(0.0, (observed_at - commit.occurred_at).total_seconds())
        score = 4 * similarities[identity] + 2 * ("goal" in reasons) + ("entity" in reasons) + math.exp(-age / 3600)
        ranked.append((score, identity))
    ranked.sort(key=lambda item: (-item[0], -records[item[1]].cursor, item[1]))
    return ranked
