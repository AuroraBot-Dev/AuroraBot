from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from src.agents.triage import TriageAgent
from src.contracts import (
    AgentContext,
    AgentDecision,
    AgentLimits,
    AgentProfile,
    Completion,
    EngineConfiguration,
    ModelRequest,
    ModelResult,
    ModelUsage,
    TaskLimits,
    TaskStatus,
    TriageLimits,
    new_amp,
)
from src.engine.runtime import EngineState, PumpResult
from src.engine.store import SQLiteRuntimeStore

if TYPE_CHECKING:
    from pathlib import Path

_SMALL_BATCH_LIMIT = 1000


def _event(summary: str, *, session_id: str = "session", data: dict[str, object] | None = None):
    return new_amp(
        event_type="message.received",
        session_id=session_id,
        summary=summary,
        data=data or {"text": summary},
        source_app="test",
        source_instance="local",
    )


def _profiles() -> tuple[AgentProfile, ...]:
    return (
        AgentProfile(
            "triage",
            "src.agents.triage:TriageAgent",
            "fast",
            frozenset(),
            can_delegate=True,
            child_profiles=frozenset({"gate"}),
            triage_control=True,
        ),
        AgentProfile(
            "gate",
            "test",
            "quality",
            frozenset(),
            can_delegate=False,
            child_profiles=frozenset(),
        ),
    )


def _configuration(workspace: Path) -> EngineConfiguration:
    return EngineConfiguration(
        str(workspace),
        _profiles(),
        AgentLimits(root_profile="triage", worker_profile="gate", lease_seconds=0.01),
        TaskLimits(4, 4, 300),
        TaskLimits(4, 4, 120),
        TriageLimits(quiet_seconds=0, max_wait_seconds=0.001),
    )


class _CompletingHandler:
    def handle(self, context: AgentContext) -> AgentDecision:
        return AgentDecision(completion=Completion(f"done: {context.agent.assignment}"))


def _state(workspace: Path) -> EngineState:
    return EngineState(_configuration(workspace), {"triage": TriageAgent(), "gate": _CompletingHandler()})


async def _admit(state: EngineState) -> PumpResult:
    ingested = await state.ingest()
    await asyncio.sleep(0.001)
    batches = await state.claim_triage_batches(8)
    created = []
    for batch in batches:
        task_id = await state.create_triage_task(batch)
        if task_id is not None:
            created.append(task_id)
    result = await state.pump()
    return PumpResult(ingested, tuple(created), result.processed_message_ids, result.failed_message_ids)


async def _settle(state: EngineState, task_id: str) -> None:
    """多轮 pump 直到 Task 终态（委派链：委派 → 子回报 → 入口完成）。"""
    for _ in range(6):
        task = state.get_task(task_id)
        if task is None or task.terminal:
            return
        await state.pump()


def test_dynamic_debounce_batches_a_session_and_deduplicates(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = SQLiteRuntimeStore(tmp_path / "runtime.sqlite3")
        store.initialize()
        limits = TriageLimits(quiet_seconds=0.2, max_wait_seconds=0.5)
        first = _event("one")
        second = _event("two")
        assert store.enqueue_inbox(first, limits)
        assert not store.enqueue_inbox(first, limits)
        await asyncio.sleep(0.01)
        assert store.enqueue_inbox(second, limits)
        assert store.claim_triage_batches(limits, 1) == ()
        await asyncio.sleep(0.21)
        batches = store.claim_triage_batches(limits, 1)
        assert len(batches) == 1
        assert [event.summary for event in batches[0].events] == ["one", "two"]

    asyncio.run(scenario())


def test_triage_task_created_from_batch_with_projection_and_state(tmp_path: Path) -> None:
    async def scenario() -> None:
        state = _state(tmp_path)
        try:
            await state.submit_amp(_event("hello"))
            await _admit(state)
            task = state.tasks()[0]
            assert task.root_summary == "hello"
            agent = state.get_agent(task.root_agent_id)
            assert agent is not None and agent.profile_id == "triage"
            assert isinstance(agent.state.get("batch_events"), list)
            with state.store.connect() as connection:
                payload = json.loads(
                    connection.execute(
                        "SELECT payload_json FROM mailbox WHERE task_id = ? AND type = 'task.started'",
                        (task.task_id,),
                    ).fetchone()[0]
                )
            assert payload["batch"]["session_id"] == "session"
            assert payload["batch"]["events"][0]["summary"] == "hello"
        finally:
            state.shutdown()

    asyncio.run(scenario())


def test_triage_process_delegates_gate_with_batch_context_and_completes(tmp_path: Path) -> None:
    async def scenario() -> None:
        state = _state(tmp_path)
        try:
            await state.submit_amp(_event("hello"))
            admitted = await _admit(state)
            task_id = admitted.admitted_task_ids[0]

            activity = (await state.claim_model_requests(1))[0]
            model_result = ModelResult(
                "fast",
                frozenset({"chat", "structured_output"}),
                "normalized",
                "",
                {
                    "action": "process",
                    "summary": "handle hello",
                    "reason": "user",
                    "memory_candidate": "prefers brevity",
                },
                ModelUsage(),
                0.0,
            )
            await state.complete_model(activity, model_result.to_dict(), None)
            await _settle(state, task_id)

            task = state.get_task(task_id)
            assert task is not None and task.status == TaskStatus.COMPLETED
            assert state.status()["inbox_events"] == 0

            with state.store.connect() as connection:
                payload = json.loads(
                    connection.execute(
                        "SELECT payload_json FROM mailbox WHERE task_id = ? AND type = 'agent.assigned'",
                        (task_id,),
                    ).fetchone()[0]
                )
            assert payload["instruction"] == "handle hello"
            assert payload["context_events"][0]["summary"] == "hello"

            entries = state.completed_memory_entries()
            candidates = [fact for entry in entries for fact in entry.fact_candidates]
            assert "prefers brevity" in candidates
        finally:
            state.shutdown()

    asyncio.run(scenario())


def test_triage_defer_returns_batch_to_deferred_and_reclaims(tmp_path: Path) -> None:
    async def scenario() -> None:
        state = _state(tmp_path)
        try:
            await state.submit_amp(_event("wait"))
            admitted = await _admit(state)
            task_id = admitted.admitted_task_ids[0]

            activity = (await state.claim_model_requests(1))[0]
            await state.complete_model(
                activity,
                ModelResult(
                    "fast",
                    frozenset({"chat", "structured_output"}),
                    "normalized",
                    "",
                    {"action": "defer", "summary": "wait", "reason": "more soon", "defer_seconds": 0.01},
                    ModelUsage(),
                    0.0,
                ).to_dict(),
                None,
            )
            await state.pump()

            task = state.get_task(task_id)
            assert task is not None and task.status == TaskStatus.CANCELLED
            assert task.termination_reason == "triage.defer"
            assert state.status()["inbox_events"] == 1

            await asyncio.sleep(0.012)
            batches = await state.claim_triage_batches(8)
            assert len(batches) == 1
            task_id = await state.create_triage_task(batches[0])
            assert task_id is not None
        finally:
            state.shutdown()

    asyncio.run(scenario())


def test_triage_discard_removes_batch_events(tmp_path: Path) -> None:
    async def scenario() -> None:
        state = _state(tmp_path)
        try:
            await state.submit_amp(_event("noise"))
            admitted = await _admit(state)
            task_id = admitted.admitted_task_ids[0]

            activity = (await state.claim_model_requests(1))[0]
            await state.complete_model(
                activity,
                ModelResult(
                    "fast",
                    frozenset({"chat", "structured_output"}),
                    "normalized",
                    "",
                    {"action": "discard", "summary": "noise", "reason": "transient"},
                    ModelUsage(),
                    0.0,
                ).to_dict(),
                None,
            )
            await state.pump()

            task = state.get_task(task_id)
            assert task is not None and task.status == TaskStatus.CANCELLED
            assert task.termination_reason == "triage.discard"
            assert state.status()["inbox_events"] == 0
        finally:
            state.shutdown()

    asyncio.run(scenario())


def test_triage_fail_open_delegates_on_model_failure(tmp_path: Path) -> None:
    async def scenario() -> None:
        state = _state(tmp_path)
        try:
            await state.submit_amp(_event("must survive"))
            admitted = await _admit(state)
            task_id = admitted.admitted_task_ids[0]

            activity = (await state.claim_model_requests(1))[0]
            await state.complete_model(activity, None, "provider unavailable")
            await _settle(state, task_id)

            task = state.get_task(task_id)
            assert task is not None and task.status == TaskStatus.COMPLETED
            assert state.status()["inbox_events"] == 0
            with state.store.connect() as connection:
                payload = json.loads(
                    connection.execute(
                        "SELECT payload_json FROM mailbox WHERE task_id = ? AND type = 'agent.assigned'",
                        (task_id,),
                    ).fetchone()[0]
                )
            assert "must survive" in payload["instruction"]
        finally:
            state.shutdown()

    asyncio.run(scenario())


def test_oversized_event_is_bounded_before_triage_and_root(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = SQLiteRuntimeStore(tmp_path / "runtime.sqlite3")
        store.initialize()
        limits = TriageLimits(
            quiet_seconds=0,
            max_wait_seconds=0.001,
            max_batch_characters=_SMALL_BATCH_LIMIT,
        )
        assert store.enqueue_inbox(_event("large", data={"text": "x" * 20000}), limits)
        await asyncio.sleep(0.001)
        batch = store.claim_triage_batches(limits, 1)[0]
        assert len(json.dumps(batch.to_dict(), ensure_ascii=False, separators=(",", ":"))) <= _SMALL_BATCH_LIMIT
        assert batch.events[0].data["truncated"] is True

    asyncio.run(scenario())


def test_triage_agent_requests_structured_output_without_tools(tmp_path: Path) -> None:
    async def scenario() -> None:
        state = _state(tmp_path)
        try:
            await state.submit_amp(_event("noise"))
            await _admit(state)
            activity = (await state.claim_model_requests(1))[0]
            request = ModelRequest.from_dict(activity.request)
            assert request.tool_choice == "none"
            assert not request.tools
            assert request.output_schema is not None
        finally:
            state.shutdown()

    asyncio.run(scenario())
