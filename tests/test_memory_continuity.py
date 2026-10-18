"""主体上下文随当前任务选择，持续积累的历史不会全部固定进窗口。"""

from __future__ import annotations

from datetime import UTC, datetime

from src.contracts import AgentDefinition, AgentTree, MemorySnapshot
from src.contracts.bot import BotSnapshot, Checkpoint, Goal, GoalStatus, WakePlan, WakeStatus
from src.contracts.memory import MemoryRequest
from src.memory.continuity import select_continuity
from src.prompt import PromptAssembler, PromptCatalog


def test_explicit_goal_keeps_complete_checkpoint_amid_large_subject_history() -> None:
    """一千项长期目标只展开指定工作的完整检查点，概览和读取入口仍可见。"""
    target = Goal(
        "aurora:goal/current",
        "核对实验",
        "已保存结果",
        checkpoint=Checkpoint(
            pending_actions=("operation-7 已发起，先核对结果",), evidence_refs=("experiment:started:7",)
        ),
    )
    history = tuple(
        Goal(f"aurora:goal/past-{index}", "其他实验" * 100, "结束", GoalStatus.COMPLETED) for index in range(1000)
    )
    now = datetime(2026, 10, 18, tzinfo=UTC)
    request = MemoryRequest(focus_goal_ids=(target.goal_id,))
    continuity = select_continuity(BotSnapshot("aurora:bot/test", 1001, (*history, target)), request)
    assert continuity.goals == (target,)
    assert dict(continuity.goal_counts) == {"active": 1, "completed": 1000}
    agent = AgentDefinition("aurora:agent/test", "判断", "aurora:prompt/agent/root", "model", frozenset(), frozenset())
    tree = AgentTree.create("tree", "root", agent, "继续核对", focus_goal_ids=(target.goal_id,))
    prompt = PromptAssembler(PromptCatalog(("你是 Aurora。",), {agent.prompt_id: "按自己的判断行动。"}))
    messages = prompt.assemble(tree, "root", memory=MemorySnapshot(now, (), continuity)).messages
    assert "operation-7 已发起，先核对结果" in messages[0].content
    assert "experiment:started:7" in messages[0].content
    assert "其他实验" not in messages[0].content
    assert "aurora:tool/bot_state" in messages[0].content


def test_default_focus_prefers_current_question_and_reports_missing_explicit_goal() -> None:
    """默认选择受当前问题影响；找不到指定目标时不会冒充恢复成功。"""
    goals = tuple(Goal(f"aurora:goal/{index}", f"检查结果 {index}", "已确认") for index in range(5))
    target = Goal("aurora:goal/release", "检查发布结果", "版本一致")
    wake = WakePlan("aurora:wake/release", datetime(2026, 10, 18, tzinfo=UTC), "核对发布", target.goal_id)
    completed = WakePlan("aurora:wake/old", wake.due_at, "旧安排", target.goal_id, WakeStatus.COMPLETED, "已经核对")
    snapshot = BotSnapshot("aurora:bot/test", 1, (*goals, target), (wake, completed))
    current = select_continuity(snapshot, MemoryRequest(query="检查发布结果"))
    assert current.goals[0] == target
    assert current.wakes == (wake,)
    missing = select_continuity(snapshot, MemoryRequest(focus_goal_ids=("aurora:goal/missing",)))
    assert missing.goals == ()
    assert missing.missing_goal_ids == ("aurora:goal/missing",)
