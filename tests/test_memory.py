# ruff: noqa: PLR2004
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from src.agents.capabilities.memory import MemoryCapability
from src.contracts import (
    MEMORY_REMEMBER_CAPABILITY,
    MemoryEntry,
    MemoryQuery,
    ToolCall,
    ToolExecutionRequest,
    ToolOutcomeStatus,
)
from src.engine.runtime import _capability_allowed
from src.memory.executor import MEMORY_REMEMBER_DESCRIPTOR, MemoryToolExecutor
from src.memory.service import MemoryService

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.agent import AgentContext


def test_service_without_memory_dir_falls_back_to_empty_context() -> None:
    service = MemoryService()
    assert service.recall(MemoryQuery("anything", "session")).session_summary == ""
    assert not service.remember(MemoryEntry("task", "session", "hello", "hi", "2026-01-01"))


def test_memory_is_idempotent_session_scoped_and_fact_bounded(tmp_path: Path) -> None:
    service = MemoryService(tmp_path)
    first = MemoryEntry(
        "task-1",
        "session",
        "用户：first question",
        "first answer",
        "2026-01-01",
        ("user prefers concise answers",),
    )
    duplicate = MemoryEntry("task-1", "session", "changed", "changed", "2026-01-03")
    second = MemoryEntry("task-2", "session", "用户：second question", None, "2026-01-02")
    other = MemoryEntry("task-3", "other", "用户：other", "other answer", "2026-01-04")

    assert service.remember(first)
    assert not service.remember(duplicate)
    assert service.remember(second)
    assert service.remember(other)

    recalled = service.recall(MemoryQuery("concise", "session", fact_limit=1))
    assert "first question" in recalled.session_summary
    assert "second question" in recalled.session_summary
    assert "other answer" not in recalled.session_summary
    assert recalled.relevant_facts == ("user prefers concise answers",)


def test_memory_snapshot_obeys_total_character_budget(tmp_path: Path) -> None:
    service = MemoryService(tmp_path)
    assert service.remember(MemoryEntry("one", "session", "x" * 100, "y" * 100, "2026-01-01", ("z" * 100,)))
    recalled = service.recall(MemoryQuery("query", "session", max_characters=32))
    assert len(recalled.session_summary) + sum(map(len, recalled.relevant_facts)) <= 32


def test_executor_writes_memory_scoped_to_session(tmp_path: Path) -> None:
    service = MemoryService(tmp_path)
    executor = MemoryToolExecutor(service)
    request = ToolExecutionRequest(
        "request-1",
        "session",
        MEMORY_REMEMBER_CAPABILITY,
        {"content": "记住：用户偏好简洁回答", "fact_candidates": ["用户偏好简洁回答"]},
    )
    outcome = asyncio.run(executor.execute_tool(request))
    assert outcome.status == ToolOutcomeStatus.SUCCEEDED
    recalled = service.recall(MemoryQuery("简洁", "session", fact_limit=4))
    assert "用户偏好简洁回答" in recalled.session_summary
    assert recalled.relevant_facts == ("用户偏好简洁回答",)


def test_executor_is_idempotent_across_recovery_replay(tmp_path: Path) -> None:
    service = MemoryService(tmp_path)
    executor = MemoryToolExecutor(service)
    request = ToolExecutionRequest(
        "request-1",
        "session",
        MEMORY_REMEMBER_CAPABILITY,
        {"content": "记住：用户偏好简洁回答"},
    )
    first = asyncio.run(executor.execute_tool(request))
    replay = asyncio.run(executor.execute_tool(request))
    assert first.status == ToolOutcomeStatus.SUCCEEDED
    assert replay.status == ToolOutcomeStatus.SUCCEEDED
    summary = service.recall(MemoryQuery("", "session")).session_summary
    assert summary.count("用户偏好简洁回答") == 1


def test_executor_rejects_missing_content(tmp_path: Path) -> None:
    executor = MemoryToolExecutor(MemoryService(tmp_path))
    outcome = asyncio.run(
        executor.execute_tool(
            ToolExecutionRequest("request-1", "session", MEMORY_REMEMBER_CAPABILITY, {"content": "  "})
        )
    )
    assert outcome.status == ToolOutcomeStatus.FAILED
    assert outcome.error is not None


def test_capability_builds_tool_request_and_validates() -> None:
    capability = MemoryCapability()
    assert capability.tool_names == frozenset({MEMORY_REMEMBER_CAPABILITY})
    assert capability.tool_definitions(cast("AgentContext", object())) == ()
    decision = capability.handle_tool(
        ToolCall("call-1", MEMORY_REMEMBER_CAPABILITY, {"content": "记住 X", "fact_candidates": ["X"]})
    )
    assert decision is not None and decision.tool_request is not None
    assert decision.tool_request.parameters == {"content": "记住 X", "fact_candidates": ["X"]}
    rejected = capability.handle_tool(ToolCall("call-2", MEMORY_REMEMBER_CAPABILITY, {}))
    assert rejected is not None and rejected.failure is not None


def test_memory_descriptor_schema_requires_content() -> None:
    assert MEMORY_REMEMBER_DESCRIPTOR.id == MEMORY_REMEMBER_CAPABILITY
    assert MEMORY_REMEMBER_DESCRIPTOR.parameters_schema["required"] == ["content"]


def test_capability_allowed_exclusion_overrides_wildcard() -> None:
    allowed = frozenset({"*", "!aurora.memory.remember"})
    assert _capability_allowed("org.aurora.dashboard.send", allowed)
    assert _capability_allowed("org.aurora.mcp.clock.read", allowed)
    assert not _capability_allowed(MEMORY_REMEMBER_CAPABILITY, allowed)
    assert _capability_allowed(MEMORY_REMEMBER_CAPABILITY, frozenset({MEMORY_REMEMBER_CAPABILITY}))
