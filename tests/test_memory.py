"""Tests for the three-layer memory system (RFC 0021)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path  # noqa: TC003

from src.agents.capabilities.memory import MEMORY_QUERY_TOOL, MEMORY_REMEMBER_TOOL, MemoryCapability
from src.agents.memory_agent import MemoryAgent
from src.contracts.agent import (
    AgentContext,
    AgentInstance,
    AgentMessage,
    AgentProfile,
    AgentStatus,
    BrainContextSnapshot,
    CapabilityDescriptor,
    MessageStatus,
    TaskState,
    TaskStatus,
)
from src.memory.service import MemoryService
from src.prompt import PromptCatalog, PromptComposer

_EXPECTED_EVENT_COUNT = 2
_EXPECTED_FACT_COUNT = 2


def _gate_profile() -> AgentProfile:
    return AgentProfile(
        "builtin.gate",
        "test",
        "fast",
        frozenset({"*"}),
        can_delegate=False,
        child_profiles=frozenset(),
    )


def _dummy_context() -> AgentContext:
    task = TaskState(
        task_id="t1",
        root_agent_id="a1",
        root_message_id="m1",
        session_id="local:console",
        root_summary="你好",
        autonomous=False,
        status=TaskStatus.ACTIVE,
        model_calls=0,
        tool_calls=0,
        max_model_calls=8,
        max_tool_calls=6,
        max_duration_seconds=300,
        started_at="now",
        updated_at="now",
    )
    agent = AgentInstance(
        "a1",
        "t1",
        None,
        "builtin.gate",
        0,
        "回应眼前的人",
        AgentStatus.READY,
        0,
        {},
        "now",
        "now",
    )
    message = AgentMessage(
        "m1",
        "t1",
        "a1",
        "task.started",
        {"amp": {"header": {}, "payload": {"data": {"text": "hi"}}}},
        None,
        "t1",
        100,
        MessageStatus.PENDING,
        "now",
        None,
        "now",
    )
    profile = _gate_profile()
    brain = BrainContextSnapshot((), (), (), "now")
    capabilities: tuple[CapabilityDescriptor, ...] = (
        CapabilityDescriptor("org.aurora.console.send", "Send text", {"type": "object", "properties": {}}),
    )
    return AgentContext(task, agent, message, (), profile, capabilities, brain)


class _FakeMemoryService:
    def __init__(self, *, available: bool = True, events: list[dict[str, str]] | None = None) -> None:
        self._available = available
        self._events = events or []

    @property
    def available(self) -> bool:
        return self._available

    def search(self, _query: str, user_id: str | None = None, limit: int = 8) -> list[str]:  # noqa: ARG002
        return ["test fact 1", "test fact 2"] if self._available else []

    def add(self, _content: str, user_id: str | None = None) -> bool:  # noqa: ARG002
        return self._available

    def recall_recent_events(self, limit: int = 10) -> list[dict[str, str]]:
        return self._events[:limit] if self._available else []


class TestMemoryService:
    def test_disabled_service_returns_empty(self) -> None:
        svc = MemoryService.disabled()
        assert not svc.available
        assert svc.search("anything") == []
        assert svc.add("anything") is False
        assert svc.recall_recent_events() == []

    def test_recall_recent_events_from_sqlite(self, tmp_path: Path) -> None:
        db_path = tmp_path / "runtime.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE causal_events (type TEXT, summary TEXT, created_at TEXT)")
        conn.execute("INSERT INTO causal_events VALUES ('task.started', 'hello', '2026-01-01T00:00:00')")
        conn.execute("INSERT INTO causal_events VALUES ('tool.succeeded', 'sent', '2026-01-01T00:01:00')")
        conn.commit()
        conn.close()

        svc = MemoryService.disabled()
        svc._db_path = db_path
        events = svc.recall_recent_events(limit=5)
        assert len(events) == _EXPECTED_EVENT_COUNT
        assert events[0]["summary"] == "sent"
        assert events[1]["summary"] == "hello"


class TestMemoryAgent:
    def test_no_memory_service_returns_unavailable(self) -> None:
        agent = MemoryAgent()
        context = _dummy_context()
        decision = agent.handle(context)
        assert decision.completion is not None
        assert decision.completion.summary == "memory unavailable"

    def test_handles_memory_query(self) -> None:
        fake_svc = _FakeMemoryService()
        agent = MemoryAgent(memory_service=fake_svc)
        instruction = json.dumps({"type": "memory.query", "query": "who am I?", "limit": 8})
        context = _dummy_context()
        context = replace(context, agent=replace(context.agent, assignment=instruction))
        decision = agent.handle(context)
        assert decision.completion is not None
        summary = json.loads(decision.completion.summary)
        assert summary["operation"] == "memory.query"
        assert summary["count"] == _EXPECTED_FACT_COUNT

    def test_handles_memory_proposal(self) -> None:
        fake_svc = _FakeMemoryService()
        agent = MemoryAgent(memory_service=fake_svc)
        instruction = json.dumps({"type": "memory.proposal", "content": "remember this"})
        context = _dummy_context()
        context = replace(context, agent=replace(context.agent, assignment=instruction))
        decision = agent.handle(context)
        assert decision.completion is not None
        summary = json.loads(decision.completion.summary)
        assert summary["operation"] == "memory.proposal"
        assert summary["stored"] is True

    def test_invalid_instruction_returns_failure(self) -> None:
        fake_svc = _FakeMemoryService()
        agent = MemoryAgent(memory_service=fake_svc)
        context = _dummy_context()
        context = replace(context, agent=replace(context.agent, assignment="not valid json{"))
        decision = agent.handle(context)
        assert decision.failure is not None

    def test_unknown_operation_returns_failure(self) -> None:
        fake_svc = _FakeMemoryService()
        agent = MemoryAgent(memory_service=fake_svc)
        instruction = json.dumps({"type": "memory.delete"})
        context = _dummy_context()
        context = replace(context, agent=replace(context.agent, assignment=instruction))
        decision = agent.handle(context)
        assert decision.failure is not None
        assert "unknown" in decision.failure


class TestPromptComposerMemory:
    def test_no_memory_does_not_add_extra_sections(self) -> None:
        catalog = PromptCatalog.create(soul="# soul", world="# world", agents={"builtin.gate": "# gate"})
        composer = PromptComposer(catalog)
        document = composer.request_document(_dummy_context())
        keys = [s.key for s in document.user_sections]
        assert "recent_events" not in keys
        assert "related_memories" not in keys

    def test_with_memory_adds_sections_when_available(self) -> None:
        catalog = PromptCatalog.create(soul="# soul", world="# world", agents={"builtin.gate": "# gate"})
        fake_svc = _FakeMemoryService(
            events=[{"created_at": "2026-01-01T00:00:00", "type": "task.started", "summary": "hello"}],
        )
        composer = PromptComposer(catalog, memory=fake_svc)
        document = composer.request_document(_dummy_context())
        keys = [s.key for s in document.user_sections]
        assert "recent_events" in keys
        assert "related_memories" in keys

    def test_disabled_memory_does_not_add_sections(self) -> None:
        catalog = PromptCatalog.create(soul="# soul", world="# world", agents={"builtin.gate": "# gate"})
        fake_svc = _FakeMemoryService(available=False)
        composer = PromptComposer(catalog, memory=fake_svc)
        document = composer.request_document(_dummy_context())
        keys = [s.key for s in document.user_sections]
        assert "recent_events" not in keys
        assert "related_memories" not in keys


class TestMemoryTools:
    def test_memory_query_tool_always_present(self) -> None:
        cap = MemoryCapability()
        tools = cap.tool_definitions(_dummy_context())
        names = [t.name for t in tools]
        assert MEMORY_QUERY_TOOL in names

    def test_memory_remember_tool_when_profile_configured(self) -> None:
        cap = MemoryCapability(agent_profile="builtin.memory")
        tools = cap.tool_definitions(_dummy_context())
        names = [t.name for t in tools]
        assert MEMORY_REMEMBER_TOOL in names

    def test_memory_remember_tool_absent_when_no_profile(self) -> None:
        cap = MemoryCapability()
        tools = cap.tool_definitions(_dummy_context())
        names = [t.name for t in tools]
        assert MEMORY_REMEMBER_TOOL not in names

    def test_memory_remember_tool_has_content_param(self) -> None:
        cap = MemoryCapability(agent_profile="builtin.memory")
        tools = cap.tool_definitions(_dummy_context())
        remember_tool = next(t for t in tools if t.name == MEMORY_REMEMBER_TOOL)
        assert "content" in remember_tool.parameters_schema["required"]
        assert "importance" in remember_tool.parameters_schema["properties"]
