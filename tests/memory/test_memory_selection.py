"""高价值经历按任务关系召回，前提和知识修订共同进入上下文。"""

from __future__ import annotations

from aurora_bot.contracts import AgentDefinition, ChatMessage, MemorySnapshot
from aurora_bot.contracts.bot import Checkpoint, Goal
from aurora_bot.contracts.memory import MemoryBundle, MemoryContinuity, MemoryRequest
from aurora_bot.memory.selection import select_memories
from aurora_bot.memory_model.rules import RuleMemoryPolicy
from aurora_bot.prompt import PromptAssembler
from tests.memory.facts import _NOW, _fact
from tests.support.prompt import make_prompt_catalog


def test_old_evidence_and_known_revision_are_kept_outside_recent_window() -> None:
    """检查点引用不受近期窗口限制，后来已知的修订一同披露。"""
    original = _fact("original", "接口旧地址", 1)
    revised = _fact("revised", "接口新地址", 2, supersedes=[original.commit_id])
    goal = Goal("aurora:goal/check", "检查接口", "地址有效", checkpoint=Checkpoint(evidence_refs=("original",)))
    continuity = MemoryContinuity("aurora:bot/test", 1, (goal,))
    selected = select_memories((original, revised), (), _request(), continuity, RuleMemoryPolicy())
    assert selected.required == (original, revised)
    assert selected.bundles == ()
    historical = select_memories((original,), (), _request(), continuity, RuleMemoryPolicy())
    assert historical.required == (original,)


def test_old_task_and_entity_candidates_recall_complete_dependency_set() -> None:
    """实体和目标关系可以找回不含查询文字的旧经历，同时补齐关键前提。"""
    support = _fact("support", "操作已经发起", 1)
    task = _fact("task", "需要核对这个状态", 2, goal_ids=["aurora:goal/check"], depends_on=["support"])
    entity = _fact("entity", "曾经出现过相同错误", 3, entity_ids=["operation-7"])
    request = _request(query="operation-7", focus_goal_ids=("aurora:goal/check",))
    selected = select_memories((support, task, entity), (), request, None, RuleMemoryPolicy())
    assert {commit.commit_id for bundle in selected.bundles for commit in bundle.commits} == {
        "support",
        "task",
        "entity",
    }
    task_bundle = next(bundle for bundle in selected.bundles if "goal" in bundle.routes)
    assert task_bundle.commits == (support, task)
    assert any("entity" in bundle.routes for bundle in selected.bundles)
    constrained = select_memories((support, task), (task,), _request(max_characters=1), None, RuleMemoryPolicy())
    assert constrained.bundles == ()


def test_missing_dependencies_are_not_presented_as_complete_evidence() -> None:
    """可选经历缺少前提时整组跳过，检查点缺少证据则明确报告。"""
    broken = _fact("broken", "尚未验证的结论", 1, depends_on=["unavailable"])
    goal = Goal("aurora:goal/check", "检查", "已确认", checkpoint=Checkpoint(evidence_refs=("unknown",)))
    continuity = MemoryContinuity("aurora:bot/test", 1, (goal,))
    selected = select_memories((broken,), (broken,), _request(), continuity, RuleMemoryPolicy())
    assert selected.bundles == ()
    assert selected.missing_refs == ("unknown",)


def test_prompt_budget_does_not_drop_shared_dependency_when_skipping_large_bundle() -> None:
    """第一组超限后，后一组仍自行携带共享前提，跨域提交也只展示一次。"""
    support = _fact("support", "已经发起，请先核对结果", 1)
    large = _fact("large", "无关细节" * 1000, 2, depends_on=["support"])
    small = _fact("small", "接下来检查状态", 3, depends_on=["support"])
    memory = MemorySnapshot(
        _NOW,
        (),
        bundles=(MemoryBundle((support, large), 2.0), MemoryBundle((support, small), 1.0)),
    )
    agent = AgentDefinition(
        "aurora:agent/definition/test",
        "判断",
        "aurora:prompt/agent/root",
        "test:ai/endpoint/model",
        frozenset(),
    )
    transcript = (ChatMessage.message("继续"),)
    assembler = PromptAssembler(
        make_prompt_catalog(("你是 Aurora。",), {agent.prompt_id: "自行判断。"}), max_characters=700
    )
    messages = assembler.assemble(agent.prompt_id, transcript, memory=memory).messages
    system = messages[0].content
    assert "已经发起，请先核对结果" in system
    assert "接下来检查状态" in system
    assert "无关细节" not in system
    assert system.count("- support ") == 1


def _request(query: str = "", focus_goal_ids: tuple[str, ...] = (), max_characters: int = 8000) -> MemoryRequest:
    """为独立排序场景固定已知前缀。"""
    return MemoryRequest(
        query=query, focus_goal_ids=focus_goal_ids, max_characters=max_characters, cursor=99, observed_at=_NOW
    )
