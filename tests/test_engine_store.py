# ruff: noqa: PLR2004
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING

import pytest

from src.agents.handler import ToolAgent
from src.contracts.agent import (
    AgentContext,
    AgentDecision,
    AgentLimits,
    AgentProfile,
    CapabilityCatalogSnapshot,
    CapabilityDescriptor,
    Completion,
    DelegationRequest,
    EngineConfiguration,
    TaskLimits,
    TaskStatus,
    ToolRequest,
)
from src.contracts.amp import new_amp
from src.contracts.model import ModelContinuation, ModelRequest, ModelResult, ModelUsage, ToolCall
from src.contracts.tool import ToolOutcomeStatus
from src.contracts.triage import TriageAction, TriageDecision, TriageLimits
from src.engine.archive import task_archive_projection
from src.engine.runtime import EngineState, PumpResult
from src.engine.store import SQLiteRuntimeStore
from src.prompt import PromptCatalog, PromptComposer

if TYPE_CHECKING:
    from pathlib import Path


def _profiles() -> tuple[AgentProfile, ...]:
    return (
        AgentProfile(
            "gate",
            "test",
            "fast",
            frozenset({"test.*"}),
            can_delegate=True,
            child_profiles=frozenset({"worker"}),
        ),
        AgentProfile(
            "worker",
            "test",
            "fast",
            frozenset({"test.*"}),
            can_delegate=True,
            child_profiles=frozenset({"worker"}),
        ),
    )


def _configuration(workspace: Path) -> EngineConfiguration:
    return EngineConfiguration(
        str(workspace),
        _profiles(),
        AgentLimits(root_profile="gate", worker_profile="worker", lease_seconds=0.01),
        TaskLimits(8, 6, 300),
        TaskLimits(3, 2, 120),
        TriageLimits(quiet_seconds=0, max_wait_seconds=0.001),
    )


def _amp(summary: str = "hello"):
    return new_amp(
        event_type="message.received",
        session_id="session",
        summary=summary,
        data={"text": summary},
        source_app="test",
        source_instance="test",
    )


class _Complete:
    def handle(self, context: AgentContext) -> AgentDecision:
        return AgentDecision(completion=Completion(f"done: {context.agent.assignment}"))


async def _admit(state: EngineState, max_turns: int | None = None) -> PumpResult:
    ingested = await state.ingest()
    await asyncio.sleep(0.001)
    batches = await state.claim_triage_batches(8)
    admitted = []
    for batch in batches:
        task_id = await state.apply_triage(
            batch,
            TriageDecision(TriageAction.PROCESS, batch.events[0].summary, "test"),
        )
        if task_id is not None:
            admitted.append(task_id)
    result = await state.pump(max_turns)
    return PumpResult(ingested, tuple(admitted), result.processed_message_ids, result.failed_message_ids)


def test_task_archive_projection_removes_replay_redundancy() -> None:
    projected = task_archive_projection(
        {
            "events": [
                {
                    "payload": {
                        "continuation": {"items": [{"large": "value"}]},
                        "tools": [{"name": "one", "parameters_schema": {"type": "object"}}],
                        "text": "kept",
                    }
                }
            ]
        }
    )
    payload = projected["events"][0]["payload"]
    assert payload == {"text": "kept", "tool_names": ["one"]}


def test_runtime_store_migrates_v5_to_incremental_vacuum(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    SQLiteRuntimeStore(database).initialize()
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE schema_meta SET version = 5")
        connection.commit()
        connection.execute("PRAGMA auto_vacuum = NONE")
        connection.execute("VACUUM")
        assert connection.execute("PRAGMA auto_vacuum").fetchone()[0] == 0

    SQLiteRuntimeStore(database).initialize()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version FROM schema_meta").fetchone()[0] == 7
        assert connection.execute("PRAGMA auto_vacuum").fetchone()[0] == 2


def test_amp_creates_archives_and_deduplicates_task(tmp_path: Path) -> None:
    state = EngineState(_configuration(tmp_path), {"gate": _Complete(), "worker": _Complete()})

    async def scenario() -> None:
        amp = _amp()
        await state.submit_amp(amp)
        first = await _admit(state)
        task_id = first.admitted_task_ids[0]
        await state.finalize_terminal_tasks()
        await state.submit_amp(amp)
        replay = await _admit(state)
        assert len(first.admitted_task_ids) == 1
        assert replay.admitted_task_ids == ()
        assert state.get_task(task_id) is None
        detail = state.task_detail(task_id)
        assert detail is not None
        assert detail["archive_version"] == 2
        assert detail["events"][0]["type"] == "task.started"
        assert (tmp_path / "archive" / "tasks" / f"{task_id}.json").is_file()

    try:
        asyncio.run(scenario())
    finally:
        state.shutdown()


def test_invalid_file_is_rejected_and_ambient_hint_still_requires_triage(tmp_path: Path) -> None:
    state = EngineState(_configuration(tmp_path), {"gate": _Complete(), "worker": _Complete()})
    invalid = tmp_path / "inbox" / "invalid.json"
    invalid.write_text("{", encoding="utf-8")

    async def scenario() -> None:
        ambient = new_amp(
            event_type="clock.changed",
            session_id="clock",
            summary="ambient fact",
            data={"ambient": True, "vendor": {"arbitrary": True}},
            source_app="clock",
            source_instance="test",
        )
        await state.submit_amp(ambient)
        result = await _admit(state)
        assert result.admitted_task_ids
        assert state.tasks()[0].root_summary == "ambient fact"
        assert (tmp_path / "archive" / "inbox" / "rejected" / "invalid.json").is_file()

    try:
        asyncio.run(scenario())
    finally:
        state.shutdown()


def test_delegation_children_report_to_parent(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.agent.parent_agent_id is None and context.message.type == "task.started":
                return AgentDecision(delegations=(DelegationRequest("first"), DelegationRequest("second")))
            if context.agent.parent_agent_id is not None:
                return AgentDecision(completion=Completion(context.agent.assignment))
            completed = int(context.agent.state.get("completed", 0)) + 1
            if completed == 1:
                return AgentDecision(wait_for_children=True, state_patch={"completed": completed})
            return AgentDecision(completion=Completion("all children reported"), state_patch={"completed": completed})

    state = EngineState(_configuration(tmp_path), {"gate": Handler(), "worker": Handler()})

    async def scenario() -> None:
        await state.submit_amp(_amp())
        await _admit(state, 8)
        await state.pump(8)
        await state.pump(1)
        assert state.tasks()[0].status == TaskStatus.ACTIVE
        await state.pump(1)
        assert state.tasks()[0].status == TaskStatus.COMPLETED
        assert len(state.store.agents()) == 3

    try:
        asyncio.run(scenario())
    finally:
        state.shutdown()


def test_tool_success_resumes_agent_and_duplicate_is_idempotent(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.message.type == "tool.succeeded":
                return AgentDecision(completion=Completion("tool handled"))
            return AgentDecision(tool_request=ToolRequest("test.reply", {"text": "hello"}))

    state = EngineState(_configuration(tmp_path), {"gate": Handler(), "worker": Handler()})
    state.install_capability_catalog(
        CapabilityCatalogSnapshot((CapabilityDescriptor("test.reply", "reply", {"type": "object"}),))
    )

    async def scenario() -> None:
        await state.submit_amp(_amp())
        result = await _admit(state)
        assert state.has_pending_tool_requests() and state.has_work()
        lease = (await state.claim_tool_requests())[0]
        kwargs = {
            "request_id": lease.request_id,
            "capability": lease.capability,
            "status": ToolOutcomeStatus.SUCCEEDED,
            "summary": "delivered",
            "result": {"ok": True},
            "error": None,
            "source_app": "test",
            "source_instance": "test",
        }
        await state.complete_tool(**kwargs)  # type: ignore[arg-type]
        await state.complete_tool(**kwargs)  # type: ignore[arg-type]
        await state.pump()
        task = state.get_task(result.admitted_task_ids[0])
        assert task is not None and task.status == TaskStatus.COMPLETED
        with pytest.raises(ValueError, match="invalid Tool outcome"):
            await state.complete_tool(**{**kwargs, "status": "forged"})  # type: ignore[arg-type]

    try:
        asyncio.run(scenario())
    finally:
        state.shutdown()


def test_engine_persists_and_executes_every_model_tool_call(tmp_path: Path) -> None:
    catalog = PromptCatalog.create(
        soul="soul",
        world="world",
        agents={"gate": "gate", "worker": "worker"},
    )
    agent = ToolAgent(composer=PromptComposer(catalog))
    state = EngineState(_configuration(tmp_path), {"gate": agent, "worker": agent})
    state.install_capability_catalog(
        CapabilityCatalogSnapshot(
            (
                CapabilityDescriptor("test.first", "first", {"type": "object"}),
                CapabilityDescriptor("test.second", "second", {"type": "object"}),
            )
        )
    )

    async def scenario() -> None:
        await state.submit_amp(_amp())
        await _admit(state)
        model_activity = (await state.claim_model_requests(1))[0]
        model_result = ModelResult(
            "model",
            frozenset({"chat", "tools"}),
            "native",
            "",
            None,
            ModelUsage(),
            0.0,
            tool_calls=(
                ToolCall("first-call", "test.first", {"value": 1}),
                ToolCall("second-call", "test.second", {"value": 2}),
            ),
            continuation=ModelContinuation(
                "provider",
                "responses",
                (
                    {"type": "function_call", "call_id": "first-call", "name": "test.first"},
                    {"type": "function_call", "call_id": "second-call", "name": "test.second"},
                ),
            ),
        )
        await state.complete_model(model_activity, model_result.to_dict(), None)
        await state.pump()

        first = (await state.claim_tool_requests())[0]
        assert first.capability == "test.first"
        await state.complete_tool(
            request_id=first.request_id,
            capability=first.capability,
            status=ToolOutcomeStatus.SUCCEEDED,
            summary="first complete",
            result={"value": 1},
            error=None,
            source_app="test",
            source_instance="test",
        )
        await state.pump()

        second = (await state.claim_tool_requests())[0]
        assert second.capability == "test.second"
        await state.complete_tool(
            request_id=second.request_id,
            capability=second.capability,
            status=ToolOutcomeStatus.SUCCEEDED,
            summary="second complete",
            result={"value": 2},
            error=None,
            source_app="test",
            source_instance="test",
        )
        await state.pump()

        resumed_activity = (await state.claim_model_requests(1))[0]
        resumed = ModelRequest.from_dict(resumed_activity.request).continuation
        assert resumed is not None
        outputs = [item for item in resumed.items if item.get("type") == "function_call_output"]
        assert [item["call_id"] for item in outputs] == ["first-call", "second-call"]
        assert state.tasks()[0].tool_calls == 2

    try:
        asyncio.run(scenario())
    finally:
        state.shutdown()


def test_complete_task_tool_finishes_without_resume(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            _ = context
            return AgentDecision(tool_request=ToolRequest("test.reply", {"text": "done"}, complete_task=True))

    state = EngineState(_configuration(tmp_path), {"gate": Handler(), "worker": Handler()})
    state.install_capability_catalog(
        CapabilityCatalogSnapshot((CapabilityDescriptor("test.reply", "reply", {"type": "object"}),))
    )

    async def scenario() -> None:
        await state.submit_amp(_amp())
        await _admit(state)
        lease = (await state.claim_tool_requests())[0]
        await state.complete_tool(
            request_id=lease.request_id,
            capability=lease.capability,
            status=ToolOutcomeStatus.SUCCEEDED,
            summary="delivered",
            result={},
            error=None,
            source_app="test",
            source_instance="test",
        )
        assert state.tasks()[0].status == TaskStatus.COMPLETED

    try:
        asyncio.run(scenario())
    finally:
        state.shutdown()


def test_model_activity_completion_and_failure_are_auditable(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.message.type == "model.completed":
                return AgentDecision(completion=Completion(str(context.message.payload["text"])))
            if context.message.type == "model.failed":
                return AgentDecision(failure=str(context.message.payload["error"]))
            return AgentDecision(model_request={"role": "fast", "messages": []})

    state = EngineState(_configuration(tmp_path), {"gate": Handler(), "worker": Handler()})

    async def scenario() -> None:
        await state.submit_amp(_amp("success"))
        await _admit(state)
        activity = (await state.claim_model_requests(1))[0]
        model_result = ModelResult("fake", frozenset({"chat"}), "normalized", "answer", None, ModelUsage(), 0)
        await state.complete_model(activity, model_result.to_dict(), None)
        await _admit(state)
        assert state.tasks()[0].status == TaskStatus.COMPLETED

        await state.submit_amp(_amp("failure"))
        await _admit(state)
        failed_activity = (await state.claim_model_requests(1))[0]
        await state.complete_model(failed_activity, None, "provider unavailable")
        failed = await state.pump()
        assert failed.processed_message_ids
        assert state.tasks()[1].status == TaskStatus.ERROR

    try:
        asyncio.run(scenario())
    finally:
        state.shutdown()


def test_handler_exception_fails_message_and_task(tmp_path: Path) -> None:
    class Broken:
        def handle(self, context: AgentContext) -> AgentDecision:
            _ = context
            raise RuntimeError("broken handler")

    state = EngineState(_configuration(tmp_path), {"gate": Broken(), "worker": Broken()})

    async def scenario() -> None:
        with pytest.raises(ValueError, match="positive"):
            await state.pump(0)
        await state.submit_amp(_amp())
        result = await _admit(state)
        assert result.failed_message_ids
        assert state.tasks()[0].status == TaskStatus.ERROR
        assert state.agent_detail(state.tasks()[0].root_agent_id) is not None
        assert state.status()["active_tasks"] == 0

    try:
        asyncio.run(scenario())
    finally:
        state.shutdown()


def test_handler_context_cannot_mutate_canonical_authorization_state(tmp_path: Path) -> None:
    canonical_profile = _profiles()[0]

    class Hostile:
        def handle(self, context: AgentContext) -> AgentDecision:
            with pytest.raises(FrozenInstanceError):
                context.profile.capabilities = frozenset({"*"})  # type: ignore[misc]
            object.__setattr__(context.profile, "capabilities", frozenset({"*"}))
            context.agent.state["forged"] = True
            context.message.payload["forged"] = True
            return AgentDecision(tool_request=ToolRequest("forbidden.send", {}))

    state = EngineState(_configuration(tmp_path), {"gate": Hostile(), "worker": _Complete()})
    state.install_capability_catalog(
        CapabilityCatalogSnapshot((CapabilityDescriptor("forbidden.send", "forbidden", {"type": "object"}),))
    )

    async def scenario() -> None:
        await state.submit_amp(_amp())
        result = await _admit(state)
        task = state.get_task(result.admitted_task_ids[0])
        agent = state.get_agent(task.root_agent_id) if task is not None else None
        assert result.failed_message_ids
        assert task is not None and task.status == TaskStatus.ERROR
        assert agent is not None and agent.state == {}
        assert state._profiles["gate"].capabilities == canonical_profile.capabilities == frozenset({"test.*"})

    try:
        asyncio.run(scenario())
    finally:
        state.shutdown()
