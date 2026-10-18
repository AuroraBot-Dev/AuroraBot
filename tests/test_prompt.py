from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.contracts import (
    AgentDefinition,
    AgentTree,
    ChatMessage,
    MemoryScopeSnapshot,
    MemorySnapshot,
    ToolCall,
    WorldCommit,
    WorldFrontier,
)
from src.contracts.bot import BotSnapshot, Checkpoint, Goal
from src.contracts.model import ContextBudgetError
from src.prompt import PromptAssembler, PromptCatalog


def _assembler(*, limit: int = 1_000) -> PromptAssembler:
    return PromptAssembler(
        PromptCatalog(
            ("You are Aurora.", "The world continues between messages."),
            {"aurora:prompt/agent/root": "Act as the root."},
        ),
        max_characters=limit,
    )


def _agent(prompt: str = "aurora:prompt/agent/root") -> AgentDefinition:
    return AgentDefinition("aurora:agent/test", "Test Agent.", prompt, "quality-model", frozenset(), frozenset())


def test_assembler_emits_one_system_then_node_transcript() -> None:
    tree = AgentTree.create("tree", "root", _agent(), "hello")
    tree = tree.append(
        "root",
        ChatMessage.assistant(tool_calls=(ToolCall("call-1", "clock", {}),)),
    )
    tree = tree.append("root", ChatMessage.tool("call-1", "12:00"))

    messages = _assembler().assemble(tree, "root")

    assert [message.role for message in messages] == ["system", "message", "assistant", "tool"]
    assert messages[0].content == ("You are Aurora.\n\nThe world continues between messages.\n\nAct as the root.")


def test_assembler_rejects_capacity_that_cannot_hold_required_context() -> None:
    tree = AgentTree.create("tree", "root", _agent(), "hello")
    limit = 10

    with pytest.raises(ContextBudgetError, match="必要上下文"):
        _assembler(limit=limit).assemble(tree, "root")


def test_assembler_preserves_initial_intent_when_trimming_old_history() -> None:
    tree = AgentTree.create("tree", "root", _agent(), "原始任务")
    tree = tree.append("root", ChatMessage.assistant("较早的回复" * 20))
    tree = tree.append("root", ChatMessage.message("最新的世界事实"))
    system_size = len("You are Aurora.\n\nThe world continues between messages.\n\nAct as the root.")
    tag = "部分对话未载入；请按检查点和证据引用恢复，必要时读取原始记录。"

    messages = _assembler(limit=system_size + len(tag) + len("最新的世界事实") + 20).assemble(tree, "root")

    assert [message.role for message in messages] == ["system", "message", "message", "message"]
    assert messages[1].content == "原始任务"
    assert messages[2].content == tag
    assert messages[3].content == "最新的世界事实"
    assert sum(len(message.content) for message in messages) <= system_size + len(tag) + len("最新的世界事实") + 20


def test_assembler_truncation_never_leaves_orphan_tool_message() -> None:
    tree = AgentTree.create("tree", "root", _agent(), "初始消息")
    tree = tree.append(
        "root",
        ChatMessage.assistant(tool_calls=(ToolCall("call-1", "clock", {}),)),
    )
    tree = tree.append("root", ChatMessage.tool("call-1", "12:00" * 20))
    tree = tree.append("root", ChatMessage.assistant("最终回复"))
    system_size = len("You are Aurora.\n\nThe world continues between messages.\n\nAct as the root.")
    tag = "部分对话未载入；请按检查点和证据引用恢复，必要时读取原始记录。"

    limit = system_size + len(tag) + len("初始消息最终回复")
    messages = _assembler(limit=limit).assemble(tree, "root")

    assert [message.role for message in messages] == ["system", "message", "message", "assistant"]
    assert messages[1].content == "初始消息"
    assert messages[2].content == tag
    assert messages[3].content == "最终回复"


def test_continuity_survives_memory_pressure_and_old_history_trimming() -> None:
    """上下文拥挤时仍保留已发起行动及其证据。"""
    now = datetime(2026, 10, 18, tzinfo=UTC)
    goal = Goal(
        "aurora:goal/check",
        "核对异步操作",
        "结果经过确认",
        checkpoint=Checkpoint(pending_actions=("operation-7 已发起，先查询结果",), evidence_refs=("started:7",)),
    )
    commit = WorldCommit("large", "environment.fact", "test", "普通经历" * 300, now, {"test": 1}, WorldFrontier())
    memory = MemorySnapshot(
        now, (MemoryScopeSnapshot("test", 1, (commit,)),), BotSnapshot("aurora:bot/test", 1, (goal,))
    )
    tree = AgentTree.create("tree", "root", _agent(), "检查结果")
    tree = tree.append("root", ChatMessage.assistant("很久以前的讨论" * 300))
    tree = tree.append("root", ChatMessage.message("恢复检查"))

    limit = 500
    messages = _assembler(limit=limit).assemble(tree, "root", memory=memory)

    assert "operation-7 已发起，先查询结果" in messages[0].content
    assert "started:7" in messages[0].content
    assert "普通经历" not in messages[0].content
    assert messages[1].content == "检查结果"
    assert messages[-1].content == "恢复检查"
    assert sum(len(message.content) for message in messages) <= limit


def test_latest_tool_batch_is_kept_whole_or_rejected() -> None:
    """容量不足时不把工具结果与发起调用拆开。"""
    tree = AgentTree.create("tree", "root", _agent(), "检查")
    tree = tree.append("root", ChatMessage.assistant(tool_calls=(ToolCall("call-1", "clock", {}),)))
    tree = tree.append("root", ChatMessage.tool("call-1", "很长的工具结果" * 100))

    with pytest.raises(ContextBudgetError, match="必要上下文"):
        _assembler(limit=200).assemble(tree, "root")


def test_assembler_rejects_missing_agent_prompt() -> None:
    tree = AgentTree.create("tree", "root", _agent("aurora:prompt/agent/missing"), "hello")

    with pytest.raises(ValueError, match="missing Agent prompt"):
        _assembler().assemble(tree, "root")


def test_assembler_injects_memory_snapshot_into_system() -> None:
    commit = WorldCommit(
        "c-1",
        "environment.message",
        "qq",
        "有人发来消息",
        datetime.now(UTC),
        {"qq:group": 1},
        WorldFrontier(),
        {"message_id": 1},
    )
    memory = MemorySnapshot(commit.occurred_at, (MemoryScopeSnapshot("qq:group", 1, (commit,)),))
    tree = AgentTree.create("tree", "root", _agent(), "hello")

    messages = _assembler().assemble(tree, "root", memory=memory)

    assert "最近时间窗口内的世界活动" in messages[0].content
    assert "scope：qq:group" in messages[0].content
    assert "有人发来消息" in messages[0].content
    assert '"message_id":1' in messages[0].content


def test_prompt_catalog_and_assembler_require_non_empty_bounds() -> None:
    with pytest.raises(ValueError, match="system fragment"):
        PromptCatalog((), {"aurora:prompt/agent/root": "prompt"})
    with pytest.raises(ValueError, match="Agent prompt"):
        PromptCatalog(("system",), {})
    with pytest.raises(ValueError, match="must be positive"):
        PromptAssembler(PromptCatalog(("system",), {"aurora:prompt/agent/root": "prompt"}), max_characters=0)
