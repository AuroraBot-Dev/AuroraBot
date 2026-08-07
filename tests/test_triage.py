from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from src.contracts import (
    AgentContext,
    AgentDecision,
    AgentLimits,
    AgentProfile,
    Completion,
    EngineConfiguration,
    TaskLimits,
    TriageAction,
    TriageDecision,
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


def test_triage_defer_discard_and_process_have_distinct_storage_effects(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = SQLiteRuntimeStore(tmp_path / "runtime.sqlite3")
        store.initialize()
        limits = TriageLimits(quiet_seconds=0, max_wait_seconds=0.001)
        budget = TaskLimits(2, 1, 30)

        assert store.enqueue_inbox(_event("wait"), limits)
        await asyncio.sleep(0.001)
        deferred = store.claim_triage_batches(limits, 1)[0]
        assert (
            store.apply_triage(
                deferred,
                TriageDecision(TriageAction.DEFER, "wait", "more context expected", defer_seconds=0.01),
                root_profile="root",
                interactive_budget=budget,
                autonomous_budget=budget,
                priority=100,
            )
            is None
        )
        assert store.claim_triage_batches(limits, 1) == ()
        await asyncio.sleep(0.012)
        discarded = store.claim_triage_batches(limits, 1)[0]
        assert (
            store.apply_triage(
                discarded,
                TriageDecision(TriageAction.DISCARD, "noise", "transient"),
                root_profile="root",
                interactive_budget=budget,
                autonomous_budget=budget,
                priority=100,
            )
            is None
        )
        assert store.counts()["inbox_events"] == 0

        assert store.enqueue_inbox(_event("do it"), limits)
        await asyncio.sleep(0.001)
        admitted = store.claim_triage_batches(limits, 1)[0]
        task_id = store.apply_triage(
            admitted,
            TriageDecision(TriageAction.PROCESS, "do it", "user request", memory_candidate="prefers brevity"),
            root_profile="root",
            interactive_budget=budget,
            autonomous_budget=budget,
            priority=100,
        )
        assert task_id is not None
        assert store.counts()["inbox_events"] == 0
        assert store.get_task(task_id) is not None
        with store.connect() as connection:
            payload = json.loads(
                connection.execute(
                    "SELECT payload_json FROM mailbox WHERE task_id = ? AND type = 'task.started'",
                    (task_id,),
                ).fetchone()[0]
            )
        assert payload["events"][0]["summary"] == "do it"
        assert payload["triage"]["memory_candidate"] == "prefers brevity"

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


def test_triage_failure_admits_user_input_instead_of_losing_it(tmp_path: Path) -> None:
    class BrokenProvider:
        async def complete(self, _request: object) -> object:
            raise RuntimeError("offline")

    class Policy:
        def request(self, _batch: object) -> object:
            return object()

        def resolve(self, _batch: object, _result: object) -> object:
            raise AssertionError

    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            return AgentDecision(completion=Completion(context.task.root_summary))

    async def scenario() -> None:
        profile = AgentProfile(
            "root",
            "unused",
            "quality",
            frozenset(),
            can_delegate=False,
            child_profiles=frozenset(),
        )
        configuration = EngineConfiguration(
            str(tmp_path / "engine"),
            (profile,),
            AgentLimits(root_profile="root", worker_profile="root"),
            TaskLimits(1, 1, 30),
            TaskLimits(1, 1, 30),
            TriageLimits(quiet_seconds=0, max_wait_seconds=0.001),
        )
        engine = AgentEngine(
            configuration,
            {"root": Handler()},
            model_provider=BrokenProvider(),  # type: ignore[arg-type]
            triage_policy=Policy(),  # type: ignore[arg-type]
        )
        engine.bind_tool_executors(())
        try:
            await engine.submit_amp(_event("must survive").to_dict())
            await asyncio.sleep(0.001)
            result = await engine.pump()
            assert len(result["admitted_task_ids"]) == 1
            assert len(result["processed_message_ids"]) == 1
        finally:
            await engine.shutdown()

    asyncio.run(scenario())
