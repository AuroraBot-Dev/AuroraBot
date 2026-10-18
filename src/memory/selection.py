"""多路候选召回与有依赖的集合组装，完整原始提交始终保留来源。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.contracts.memory import MemoryBundle, MemoryScore
from src.contracts.memory_graph import MemoryCandidate, MemoryRankingRequest
from src.contracts.memory_graph_codec import ranking_fingerprint
from src.memory.graph import graph_interactions
from src.memory.records import memory_links, memory_text
from src.utils.features import text_similarity

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.contracts.memory import MemoryContinuity, MemoryRequest
    from src.contracts.pkgs.memory import MemoryPolicy
    from src.contracts.world import WorldCommit

_CANDIDATES_PER_ROUTE = 32


@dataclass(frozen=True, slots=True)
class MemorySelection:
    """区分恢复所需证据、可选记忆集合与无法取得的引用。"""

    required: tuple[WorldCommit, ...]
    bundles: tuple[MemoryBundle, ...]
    missing_refs: tuple[str, ...]
    ranking: tuple[MemoryScore, ...]
    input_digest: str


def select_memories(
    history: tuple[WorldCommit, ...],
    recent: tuple[WorldCommit, ...],
    request: MemoryRequest,
    continuity: MemoryContinuity | None,
    policy: MemoryPolicy,
    *,
    evidence_history: tuple[WorldCommit, ...] = (),
) -> MemorySelection:
    """从近期、文本、目标和实体四路召回，再整体补全证据依赖。"""
    if request.observed_at is None or request.cursor is None:
        raise ValueError("记忆选择需要冻结的获知边界")
    records = {commit.commit_id: commit for commit in history}
    records.update((commit.commit_id, commit) for commit in evidence_history)
    routes, similarities = _candidate_routes(history, recent, request, continuity)
    replacements: dict[str, list[str]] = defaultdict(list)
    for commit in records.values():
        for old in memory_links(commit, "supersedes"):
            replacements[old].append(commit.commit_id)
    required_refs = (
        tuple(ref for goal in continuity.goals for ref in goal.checkpoint.evidence_refs) if continuity else ()
    )
    required, missing = _closure(required_refs, records, replacements)
    required_ids = {commit.commit_id for commit in required}
    included = {commit.commit_id for commit in required}
    routes = {key: reasons for key, reasons in routes.items() if key not in replacements or key in required_refs}
    ranked, input_digest = _rank_candidates(history, routes, similarities, request, policy)
    budget = request.max_characters
    bundles: list[MemoryBundle] = []
    for item in ranked:
        score, identity = item.score, item.memory_id
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
    return MemorySelection(required, tuple(bundles), missing, tuple(ranked), input_digest)


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
    history: tuple[WorldCommit, ...],
    routes: Mapping[str, set[str]],
    similarities: Mapping[str, float],
    request: MemoryRequest,
    policy: MemoryPolicy,
) -> tuple[list[MemoryScore], str]:
    """多路召回与学习排序共用可见候选和历史图前缀。"""
    if request.cursor is None or request.observed_at is None:
        raise ValueError("记忆排序需要明确游标和观察时间")
    candidates = []
    for commit in history:
        if commit.commit_id not in routes:
            continue
        if commit.recorded_at is None:
            raise ValueError("记忆候选缺少获知时间")
        reasons = routes[commit.commit_id]
        candidates.append(
            MemoryCandidate(
                commit.commit_id,
                memory_text(commit),
                commit.cursor,
                commit.occurred_at,
                commit.recorded_at,
                similarities[commit.commit_id],
                "goal" in reasons,
                "entity" in reasons,
            )
        )
    ranking = MemoryRankingRequest(
        request.query,
        request.focus_goal_ids,
        request.cursor,
        request.observed_at,
        tuple(candidates),
        graph_interactions(history),
    )
    scores = policy.score(ranking)
    ranked = [
        MemoryScore(
            candidates[index].memory_id,
            scores[index],
            candidates[index].similarity,
            tuple(sorted(routes[candidates[index].memory_id])),
        )
        for index in ranking.ranked_indices(scores)
    ]
    return ranked, ranking_fingerprint(ranking)
