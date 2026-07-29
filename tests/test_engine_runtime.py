"""AgentEngine 最小因果闭环。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.agents.triage import StructuredTriagePolicy
from src.contracts.agent import (
    AgentContext,
    AgentDecision,
    AgentLimits,
    AgentProfile,
    Completion,
    EngineConfiguration,
    TaskLimits,
)
from src.contracts.amp import new_amp
from src.contracts.memory import MemoryContextSnapshot, MemoryEntry, MemoryQuery
from src.contracts.model import ModelResult, ModelUsage
from src.contracts.triage import TriageLimits
from src.engine.runtime import AgentEngine

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.model import ModelRequest


class _CompletingHandler:
    def handle(self, context: AgentContext) -> AgentDecision:
        return AgentDecision(completion=Completion(f"completed: {context.task.root_summary}"))


class _UnusedModelProvider:
    async def complete(self, request: ModelRequest) -> ModelResult:
        return ModelResult(
            request.role,
            frozenset({"chat", "structured_output"}),
            "normalized",
            "",
            {"action": "process", "summary": "hello", "reason": "test"},
            ModelUsage(),
            0.0,
        )


def test_engine_owns_complete_pump(tmp_path: Path) -> None:
    async def exercise() -> None:
        profile = AgentProfile(
            id="test.root",
            implementation="unused",
            model_role="test",
            capabilities=frozenset(),
            can_delegate=False,
            child_profiles=frozenset(),
        )
        limits = AgentLimits(root_profile=profile.id, worker_profile=profile.id)
        configuration = EngineConfiguration(
            workspace=str(tmp_path / "engine"),
            profiles=(profile,),
            limits=limits,
            interactive_budget=TaskLimits(1, 1, 30.0),
            autonomous_budget=TaskLimits(1, 1, 30.0),
            triage=TriageLimits(quiet_seconds=0, max_wait_seconds=0.001),
        )
        engine = AgentEngine(
            configuration,
            {profile.id: _CompletingHandler()},
            model_provider=_UnusedModelProvider(),
            triage_policy=StructuredTriagePolicy(configuration.triage),
        )
        engine.bind_tool_executors(())
        try:
            message_id = await engine.submit_amp(
                new_amp(
                    event_type="message.received",
                    session_id="test-session",
                    summary="hello",
                    data={"text": "hello"},
                    source_app="test",
                    source_instance="local",
                ).to_dict()
            )
            result = await engine.pump()

            assert message_id
            assert len(result["admitted_task_ids"]) == 1
            assert len(result["processed_message_ids"]) == 1
            task = engine.task_detail(result["admitted_task_ids"][0])
            assert task is not None
            assert task["task"]["status"] == "COMPLETED"
        finally:
            await engine.shutdown()

    asyncio.run(exercise())


def test_engine_recalls_before_handler_and_remembers_only_interactive_completion(tmp_path: Path) -> None:
    events: list[tuple[str, object]] = []

    class Memory:
        def recall(self, query: MemoryQuery) -> MemoryContextSnapshot:
            events.append(("recall", query))
            return MemoryContextSnapshot(relevant_facts=(f"memory:{query.query}",))

        def remember(self, entry: MemoryEntry) -> bool:
            events.append(("remember", entry))
            return True

    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            events.append(("handler", context.task.root_summary))
            assert context.memory.relevant_facts == (f"memory:{context.task.root_summary}",)
            return AgentDecision(completion=Completion(f"completed: {context.task.root_summary}"))

    async def exercise() -> None:
        profile = AgentProfile(
            "test.root",
            "unused",
            "test",
            frozenset(),
            can_delegate=False,
            child_profiles=frozenset(),
        )
        configuration = EngineConfiguration(
            workspace=str(tmp_path / "engine"),
            profiles=(profile,),
            limits=AgentLimits(root_profile=profile.id, worker_profile=profile.id),
            interactive_budget=TaskLimits(1, 1, 30.0),
            autonomous_budget=TaskLimits(1, 1, 30.0),
            triage=TriageLimits(quiet_seconds=0, max_wait_seconds=0.001),
        )
        engine = AgentEngine(
            configuration,
            {profile.id: Handler()},
            model_provider=_UnusedModelProvider(),
            triage_policy=StructuredTriagePolicy(configuration.triage),
            memory_store=Memory(),
        )
        engine.bind_tool_executors(())
        try:
            await engine.submit_amp(
                new_amp(
                    event_type="message.received",
                    session_id="interactive",
                    summary="hello",
                    data={"text": "hello"},
                    source_app="test",
                    source_instance="local",
                ).to_dict()
            )
            interactive = await engine.pump()
            interactive_id = interactive["admitted_task_ids"][0]
            assert [name for name, _value in events[:2]] == ["recall", "handler"]
            remembered = [value for name, value in events if name == "remember"]
            assert [entry.task_id for entry in remembered if isinstance(entry, MemoryEntry)] == [interactive_id]
            recalled = next(value for name, value in events if name == "recall")
            assert isinstance(recalled, MemoryQuery) and recalled.scope == "interactive"

            events.clear()
            await engine.submit_amp(
                new_amp(
                    event_type="system.tick",
                    session_id="autonomy",
                    summary="tick",
                    data={},
                    source_app="engine",
                    source_instance="local",
                ).to_dict()
            )
            autonomous = await engine.pump()
            autonomous_id = autonomous["admitted_task_ids"][0]
            assert [name for name, _value in events[:2]] == ["recall", "handler"]
            remembered = [value for name, value in events if name == "remember"]
            assert all(isinstance(entry, MemoryEntry) and entry.task_id != autonomous_id for entry in remembered)
        finally:
            await engine.shutdown()

    asyncio.run(exercise())
