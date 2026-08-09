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
from src.engine.runtime import AgentEngine
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
        AgentLimits(root_profile="triage", worker_profile="gate"),
        TaskLimits(4, 4, 300),
        TaskLimits(4, 4, 120),
        TriageLimits(quiet_seconds=0, max_wait_seconds=0.001),
    )


class _CompletingHandler:
    def handle(self, context: AgentContext) -> AgentDecision:
        return AgentDecision(completion=Completion(f"done: {context.agent.assignment}"))


class _StructuredProvider:
    """按请求序号返回预设结果：首个请求返回 triage 决策，其余返回 process。"""

    def __init__(self, first: dict[str, object] | None = None, *, fail_first: bool = False) -> None:
        self._first = first
        self._fail_first = fail_first
        self._calls = 0

    async def complete(self, request: ModelRequest) -> ModelResult:
        self._calls += 1
        if self._fail_first and self._calls == 1:
            raise RuntimeError("offline")
        data = (
            self._first
            if self._calls == 1 and self._first is not None
            else {
                "action": "process",
                "summary": "test batch",
                "reason": "test input",
            }
        )
        return ModelResult(
            request.role,
            frozenset({"chat", "structured_output"}),
            "normalized",
            "",
            data,
            ModelUsage(),
            0.0,
        )


def _engine(workspace: Path, provider: _StructuredProvider) -> AgentEngine:
    engine = AgentEngine(
        _configuration(workspace),
        {"triage": TriageAgent(), "gate": _CompletingHandler()},
        model_provider=provider,
    )
    engine.bind_tool_executors(())
    return engine


async def _pump_until_terminal(engine: AgentEngine, task_id: str, max_rounds: int = 20) -> None:
    for _ in range(max_rounds):
        task = engine.get_task(task_id)
        if task is None or task.terminal:
            return
        await engine.pump()
        await asyncio.sleep(0)  # 让模型派发后台任务完成
    raise AssertionError("task did not reach terminal state")


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


def test_recovery_preserves_active_task_batch_and_requeues_only_orphan_claim(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = SQLiteRuntimeStore(tmp_path / "runtime.sqlite3")
        store.initialize()
        limits = TriageLimits(quiet_seconds=0, max_wait_seconds=0.001)
        assert store.enqueue_inbox(_event("active", session_id="active"), limits)
        assert store.enqueue_inbox(_event("orphan", session_id="orphan"), limits)
        await asyncio.sleep(0.001)
        batches = store.claim_triage_batches(limits, 2)
        by_session = {batch.session_id: batch for batch in batches}
        active_batch = by_session["active"]
        orphan_batch = by_session["orphan"]
        created = store.create_triage_task(
            active_batch,
            triage_profile="triage",
            interactive_budget=TaskLimits(4, 4, 300),
            autonomous_budget=TaskLimits(4, 4, 120),
            priority=100,
        )
        assert created is not None

        store.recover_interrupted()
        with store.connect() as connection:
            active = connection.execute(
                "SELECT status, batch_id FROM inbox_events WHERE session_id = 'active'"
            ).fetchone()
            orphan = connection.execute(
                "SELECT status, batch_id FROM inbox_events WHERE session_id = 'orphan'"
            ).fetchone()
        assert active is not None and active["status"] == "TRIAGING"
        assert active["batch_id"] == active_batch.batch_id
        assert orphan is not None and orphan["status"] == "PENDING"
        assert orphan["batch_id"] is None
        assert orphan_batch.batch_id != active_batch.batch_id

    asyncio.run(scenario())


def test_triage_process_delegates_gate_with_batch_context_and_completes(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine = _engine(
            tmp_path,
            _StructuredProvider(
                {
                    "action": "process",
                    "summary": "handle hello",
                    "reason": "user",
                    "memory_candidate": "prefers brevity",
                }
            ),
        )
        try:
            await engine.submit_amp(_event("hello").to_dict())
            await asyncio.sleep(0.001)
            result = await engine.pump()
            task_id = result["admitted_task_ids"][0]
            await _pump_until_terminal(engine, task_id)

            task = engine.get_task(task_id)
            assert task is not None and task.status == TaskStatus.COMPLETED
            assert engine.status()["inbox_events"] == 0

            with engine.store.connect() as connection:
                payload = json.loads(
                    connection.execute(
                        "SELECT payload_json FROM messages WHERE task_id = ? AND type = 'agent.assigned'",
                        (task_id,),
                    ).fetchone()[0]
                )
            assert payload["instruction"] == "handle hello"
            assert payload["context_events"][0]["summary"] == "hello"

            entries = engine.completed_memory_entries()
            candidates = [fact for entry in entries for fact in entry.fact_candidates]
            assert "prefers brevity" in candidates
        finally:
            await engine.shutdown()

    asyncio.run(scenario())


def test_triage_routes_process_to_fast_or_root_and_falls_back_to_root(tmp_path: Path) -> None:
    async def route_once(route: str, expected: str) -> None:
        profiles = (
            AgentProfile(
                "triage",
                "src.agents.triage:TriageAgent",
                "fast",
                frozenset(),
                can_delegate=True,
                child_profiles=frozenset({"builtin.fast", "builtin.root"}),
                triage_control=True,
            ),
            AgentProfile(
                "builtin.fast",
                "test",
                "fast",
                frozenset({"*"}),
                can_delegate=False,
                child_profiles=frozenset(),
            ),
            AgentProfile(
                "builtin.root",
                "test",
                "quality",
                frozenset({"*"}),
                can_delegate=False,
                child_profiles=frozenset(),
            ),
        )
        configuration = EngineConfiguration(
            str(tmp_path / route.replace(".", "-")),
            profiles,
            AgentLimits(root_profile="triage", worker_profile="builtin.root"),
            TaskLimits(4, 4, 300),
            TaskLimits(4, 4, 120),
            TriageLimits(quiet_seconds=0, max_wait_seconds=0.001),
        )
        engine = AgentEngine(
            configuration,
            {
                "triage": TriageAgent(),
                "builtin.fast": _CompletingHandler(),
                "builtin.root": _CompletingHandler(),
            },
            model_provider=_StructuredProvider(
                {
                    "action": "process",
                    "summary": "handle now",
                    "reason": "user input",
                    "delegate_profile": route,
                }
            ),
        )
        engine.bind_tool_executors(())
        try:
            await engine.submit_amp(_event("hello").to_dict())
            await asyncio.sleep(0.001)
            result = await engine.pump()
            task_id = result["admitted_task_ids"][0]
            await _pump_until_terminal(engine, task_id)
            with engine.store.connect() as connection:
                selected = connection.execute(
                    "SELECT profile_id FROM agents WHERE task_id = ? AND parent_agent_id IS NOT NULL",
                    (task_id,),
                ).fetchone()[0]
            assert selected == expected
        finally:
            await engine.shutdown()

    async def scenario() -> None:
        await route_once("builtin.fast", "builtin.fast")
        await route_once("builtin.root", "builtin.root")
        await route_once("unknown", "builtin.root")

    asyncio.run(scenario())


def test_triage_defer_returns_batch_to_deferred_and_reclaims(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine = _engine(
            tmp_path,
            _StructuredProvider({"action": "defer", "summary": "wait", "reason": "more soon", "defer_seconds": 0.01}),
        )
        try:
            await engine.submit_amp(_event("wait").to_dict())
            await asyncio.sleep(0.001)
            result = await engine.pump()
            task_id = result["admitted_task_ids"][0]
            await _pump_until_terminal(engine, task_id)

            task = engine.get_task(task_id)
            assert task is not None and task.status == TaskStatus.CANCELLED
            assert task.termination_reason == "triage.defer"
            assert engine.status()["inbox_events"] == 1

            await asyncio.sleep(0.012)
            batches = engine.store.claim_triage_batches(engine.configuration.triage, 8)
            assert len(batches) == 1
            created = engine.store.create_triage_task(
                batches[0],
                triage_profile="triage",
                interactive_budget=engine.configuration.interactive_budget,
                autonomous_budget=engine.configuration.autonomous_budget,
                priority=100,
            )
            assert created is not None
        finally:
            await engine.shutdown()

    asyncio.run(scenario())


def test_triage_discard_removes_batch_events(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine = _engine(
            tmp_path, _StructuredProvider({"action": "discard", "summary": "noise", "reason": "transient"})
        )
        try:
            await engine.submit_amp(_event("noise").to_dict())
            await asyncio.sleep(0.001)
            result = await engine.pump()
            task_id = result["admitted_task_ids"][0]
            await _pump_until_terminal(engine, task_id)

            task = engine.get_task(task_id)
            assert task is not None and task.status == TaskStatus.CANCELLED
            assert task.termination_reason == "triage.discard"
            assert engine.status()["inbox_events"] == 0
        finally:
            await engine.shutdown()

    asyncio.run(scenario())


def test_triage_fail_open_delegates_on_model_failure(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine = _engine(tmp_path, _StructuredProvider(fail_first=True))
        try:
            await engine.submit_amp(_event("must survive").to_dict())
            await asyncio.sleep(0.001)
            result = await engine.pump()
            task_id = result["admitted_task_ids"][0]
            await _pump_until_terminal(engine, task_id)

            task = engine.get_task(task_id)
            assert task is not None and task.status == TaskStatus.COMPLETED
            assert engine.status()["inbox_events"] == 0
            with engine.store.connect() as connection:
                payload = json.loads(
                    connection.execute(
                        "SELECT payload_json FROM messages WHERE task_id = ? AND type = 'agent.assigned'",
                        (task_id,),
                    ).fetchone()[0]
                )
            assert "must survive" in payload["instruction"]
        finally:
            await engine.shutdown()

    asyncio.run(scenario())


def test_triage_agent_requests_structured_output_without_tools(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine = _engine(tmp_path, _StructuredProvider({"action": "discard", "summary": "x", "reason": "y"}))
        try:
            await engine.submit_amp(_event("noise").to_dict())
            await asyncio.sleep(0.001)
            await engine.pump()
            rows = engine.store.claim_activities("model", 1)
            assert rows
            request = ModelRequest.from_dict(json.loads(rows[0].request_json))
            assert request.tool_choice == "none"
            assert not request.tools
            assert request.output_schema is not None
            assert request.cancel_policy == "supersedable"
        finally:
            await engine.shutdown()

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
