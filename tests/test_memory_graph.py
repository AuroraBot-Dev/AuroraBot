"""图投影和评分契约严格区分当时已知的信息与后续反馈。"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from test_memory_selection import _NOW, _fact

from src.contracts.memory import MemoryRequest
from src.contracts.memory_graph import MemoryCandidate, MemoryRankingRequest
from src.memory.graph import graph_interactions
from src.memory.selection import select_memories
from src.memory_model.dataset import MemoryEpisode, MemoryExample
from src.memory_model.evaluation import evaluate_policy
from src.memory_model.rules import RuleMemoryPolicy


def test_graph_does_not_backfill_future_node_text_or_result_feedback() -> None:
    """引用后来才出现的节点时只建立身份，不把后来的内容放入早期消息。"""
    first = _fact("first", "最初的判断", 1, depends_on=["later"], goal_ids=["aurora:goal/check"])
    later = _fact("later", "后来取得的证据", 2)
    feedback = replace(
        _fact("feedback", "确认这条证据有帮助", 3),
        kind="memory.feedback",
        data={"goal_id": "aurora:goal/check", "memory_id": "later", "helpful": True},
    )
    events = graph_interactions((first, later, feedback))
    early = tuple(event for event in events if event.cursor == first.cursor)
    dependency = next(event for event in early if event.relation == "depends_on")
    assert dependency.target.text == ""
    assert dependency.target.identity == later.commit_id
    assert not any(event.relation == "useful" for event in graph_interactions((first, later)))
    assert events[-1].relation == "useful"
    assert "后来取得的证据" in events[-1].target.text
    assert events[-1].source.kind == "goal"
    assert events[-1].target.kind == "memory"


def test_ranking_input_rejects_result_leakage_and_rule_scores_ignore_history() -> None:
    """真实标签可在以后成为历史，不能用于产生同一次推荐。"""
    fact = _fact("fact", "已知证据", 1)
    candidate = MemoryCandidate("fact", fact.summary, 1, fact.occurred_at, _NOW - timedelta(hours=2), 1.0)
    request = MemoryRankingRequest("已知证据", (), 1, _NOW, (candidate,), graph_interactions((fact,)))
    policy = RuleMemoryPolicy()
    assert len(policy.score(request)) == 1
    future = _fact("result", "成功反馈", 2)
    with pytest.raises(ValueError, match="未来反馈"):
        replace(request, interactions=graph_interactions((fact, future)))
    with pytest.raises(ValueError, match="未来候选"):
        replace(request, candidates=(replace(candidate, cursor=2),))
    with pytest.raises(ValueError, match="获知顺序"):
        replace(request, cursor=2, interactions=graph_interactions((future, fact)))


def test_offline_metrics_use_the_same_tie_choice_as_online_recall() -> None:
    """等分时旧输入顺序不能让离线报告评价另一条记忆。"""
    old = _fact("older", "相同内容", 1)
    new = _fact("newer", "相同内容", 2)
    candidates = tuple(
        MemoryCandidate(commit.commit_id, commit.summary, commit.cursor, commit.occurred_at, _NOW)
        for commit in (old, new)
    )
    ranking = MemoryRankingRequest("", (), 2, _NOW, candidates, graph_interactions((old, new)))
    example = MemoryExample(ranking, (0.0, 1.0), 3, _NOW + timedelta(seconds=1))
    metrics = evaluate_policy(RuleMemoryPolicy(), (MemoryEpisode("ties", "aurora:bot/test", (example,)),))
    selected = select_memories(
        (old, new),
        (old, new),
        MemoryRequest(cursor=2, observed_at=_NOW),
        None,
        RuleMemoryPolicy(),
    )
    assert selected.ranking[0].memory_id == "newer"
    assert metrics["top1_accuracy"] == 1.0
    assert metrics["regret"] == 0.0
