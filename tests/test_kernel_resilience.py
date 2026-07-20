from __future__ import annotations

import asyncio
import sqlite3
from typing import TYPE_CHECKING

import pytest

from src.contracts.agent import (
    ActivityStatus,
    AgentContext,
    AgentDecision,
    AgentLimits,
    AgentProfile,
    CapabilityCatalogSnapshot,
    CapabilityDescriptor,
    Completion,
    EffectRequest,
    KernelConfiguration,
    TaskBudget,
    TaskStatus,
)
from src.contracts.amp import AmpEnvelope, new_amp
from src.kernel.runtime import AgentKernel
from src.kernel.store import SQLiteRuntimeStore, utc_now
from src.kernel.store_schema import _SCHEMA, _SCHEMA_VERSION

if TYPE_CHECKING:
    from pathlib import Path


class ModelHandler:
    def handle(self, context: AgentContext) -> AgentDecision:
        if context.message.type == "model.failed":
            return AgentDecision(completion=Completion(str(context.message.payload["error"]), silent=True))
        return AgentDecision(model_request={"role": "fast", "messages": []})


class EffectHandler:
    def handle(self, context: AgentContext) -> AgentDecision:
        if context.message.type == "effect.failed":
            return AgentDecision(completion=Completion("effect failed", silent=True))
        return AgentDecision(effect_request=EffectRequest("test.reply", {"text": "hello"}))


def config(workspace: Path) -> KernelConfiguration:
    profile = AgentProfile(
        "gate",
        "test",
        "fast",
        "gate",
        frozenset(),
        can_delegate=False,
        child_profiles=frozenset(),
    )
    return KernelConfiguration(
        str(workspace),
        "persona",
        "hash",
        (profile,),
        AgentLimits(root_profile="gate", worker_profile="gate"),
        TaskBudget(8, 6, 300),
        TaskBudget(3, 2, 120),
    )


def effect_kernel(workspace: Path) -> AgentKernel:
    profile = AgentProfile(
        "gate",
        "test",
        "fast",
        "gate",
        frozenset({"test.reply"}),
        can_delegate=False,
        child_profiles=frozenset(),
    )
    configuration = KernelConfiguration(
        str(workspace),
        "persona",
        "hash",
        (profile,),
        AgentLimits(root_profile="gate", worker_profile="gate"),
        TaskBudget(8, 6, 300),
        TaskBudget(3, 2, 120),
    )
    kernel = AgentKernel(configuration, {"gate": EffectHandler()})
    kernel.install_capability_catalog(
        CapabilityCatalogSnapshot((CapabilityDescriptor("test.reply", "reply", {"type": "object"}),))
    )
    return kernel


def test_interrupted_activity_becomes_failure_message_on_restart(tmp_path: Path) -> None:
    first = AgentKernel(config(tmp_path), {"gate": ModelHandler()})

    async def first_run() -> str:
        await first.submit_amp(
            new_amp(
                event_type="message.received",
                session_id="session",
                summary="hello",
                data={},
                source_app="test",
                source_instance="test",
            )
        )
        await first.pump()
        activity = (await first.claim_model_requests(1))[0]
        assert activity.status == ActivityStatus.PROCESSING
        return activity.task_id

    task_id = asyncio.run(first_run())
    restarted = AgentKernel(config(tmp_path), {"gate": ModelHandler()})

    async def second_run() -> None:
        result = await restarted.pump()
        assert result.processed_message_ids
        assert restarted.get_task(task_id).terminal  # type: ignore[union-attr]
        events = restarted.store.events_for_task(task_id)
        assert any(event["type"] == "agent.complete" for event in events)

    asyncio.run(second_run())


def test_mailbox_claim_is_recovered_without_duplicate_task(tmp_path: Path) -> None:
    kernel = AgentKernel(config(tmp_path), {"gate": ModelHandler()})

    async def prepare() -> str:
        amp = new_amp(
            event_type="message.received",
            session_id="session",
            summary="hello",
            data={},
            source_app="test",
            source_instance="test",
        )
        await kernel.submit_amp(amp)
        kernel.ingest_ready()
        claim = kernel.store.claim_message(30)
        assert claim is not None
        return amp.header.message_id

    message_id = asyncio.run(prepare())
    restarted = AgentKernel(config(tmp_path), {"gate": ModelHandler()})

    async def recover() -> None:
        result = await restarted.pump()
        assert result.processed_message_ids
        replay = new_amp(
            event_type="message.received",
            session_id="session",
            summary="hello",
            data={},
            source_app="test",
            source_instance="test",
        ).to_dict()
        replay["header"]["message_id"] = message_id
        await restarted.submit_amp(AmpEnvelope.parse(replay))
        await restarted.pump()
        assert len(restarted.tasks()) == 1

    asyncio.run(recover())


def test_legacy_active_workspace_is_rejected_without_deletion(tmp_path: Path) -> None:
    legacy = tmp_path / "process" / "episodes"
    legacy.mkdir(parents=True)
    source = legacy / "active.json"
    source.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="legacy Episode/Graph workspace"):
        AgentKernel(config(tmp_path), {"gate": ModelHandler()})
    assert source.exists()


def test_waiting_model_agent_does_not_claim_an_unrelated_message(tmp_path: Path) -> None:
    kernel = AgentKernel(config(tmp_path), {"gate": ModelHandler()})

    async def scenario() -> None:
        await kernel.submit_amp(
            new_amp(
                event_type="message.received",
                session_id="session",
                summary="hello",
                data={},
                source_app="test",
                source_instance="test",
            )
        )
        result = await kernel.pump()
        task = kernel.get_task(result.ingested_task_ids[0])
        assert task is not None
        with kernel.store.transaction() as connection:
            kernel.store._insert_message(
                connection,
                task_id=task.task_id,
                target_agent_id=task.root_agent_id,
                message_type="child.completed",
                payload={"summary": "unrelated"},
                causation_id=None,
                correlation_id=task.task_id,
                priority=100,
                now=utc_now(),
            )
        assert kernel.store.claim_message(30) is None

    try:
        asyncio.run(scenario())
    finally:
        kernel.shutdown()


def test_late_effect_receipt_cannot_resurrect_a_cancelled_task(tmp_path: Path) -> None:
    kernel = effect_kernel(tmp_path)

    async def scenario() -> None:
        await kernel.submit_amp(
            new_amp(
                event_type="message.received",
                session_id="session",
                summary="hello",
                data={},
                source_app="test",
                source_instance="test",
            )
        )
        result = await kernel.pump()
        task_id = result.ingested_task_ids[0]
        lease = (await kernel.claim_effect_requests())[0]
        await kernel.cancel_task(task_id, "test_cancel")
        await kernel.submit_amp(
            new_amp(
                event_type="effect.succeeded",
                session_id="session",
                summary="late",
                data={
                    "request_id": lease.request_id,
                    "capability": "test.reply",
                    "result": {"ok": True},
                },
                source_app="test.platform",
                source_instance="test",
            )
        )
        await kernel.pump()

        task = kernel.get_task(task_id)
        assert task is not None and task.status == TaskStatus.CANCELLED
        assert any(event["type"] == "effect.receipt_ignored" for event in kernel.store.events_for_task(task_id))
        assert not kernel.store.situations()

    try:
        asyncio.run(scenario())
    finally:
        kernel.shutdown()


def test_pending_effect_is_work_after_restart(tmp_path: Path) -> None:
    first = effect_kernel(tmp_path)

    async def prepare() -> None:
        await first.submit_amp(
            new_amp(
                event_type="message.received",
                session_id="session",
                summary="hello",
                data={},
                source_app="test",
                source_instance="test",
            )
        )
        await first.pump()

    asyncio.run(prepare())
    first.shutdown()
    restarted = effect_kernel(tmp_path)
    try:
        assert restarted.has_pending_effect_requests()
        assert restarted.has_work()
    finally:
        restarted.shutdown()


def test_v3_audience_migration_isolates_each_legacy_task_and_situation(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    legacy_schema = _SCHEMA.replace("    audience_ref TEXT NOT NULL,\n", "").replace(
        "    PRIMARY KEY (task_id, endpoint_id, route_ref),\n    UNIQUE (endpoint_id, route_ref)\n",
        "    PRIMARY KEY (task_id, endpoint_id, route_ref)\n",
    )
    with sqlite3.connect(database) as connection:
        connection.executescript(legacy_schema)
        connection.execute("INSERT INTO schema_meta(version) VALUES (3)")
        for index in range(2):
            task_id = f"task-{index}"
            connection.execute(
                "INSERT INTO tasks (task_id, root_agent_id, root_message_id, session_id, root_summary, autonomous, "
                "status, model_calls, tool_calls, max_model_calls, max_tool_calls, max_duration_seconds, started_at, "
                "updated_at, termination_reason) VALUES (?, ?, ?, 'legacy', 'legacy', 0, 'ACTIVE', 0, 0, 1, 1, "
                "300, ?, ?, NULL)",
                (task_id, f"agent-{index}", f"message-{index}", utc_now(), utc_now()),
            )
            connection.execute(
                "INSERT INTO situations (situation_id, source, type, summary, payload_json, priority, status, "
                "claimed_by_agent_id, expires_at, created_at, updated_at) VALUES (?, 'legacy', 'external', "
                "'legacy', '{}', 1, 'OPEN', NULL, ?, ?, ?)",
                (f"situation-{index}", "2999-01-01T00:00:00+00:00", utc_now(), utc_now()),
            )

    store = SQLiteRuntimeStore(database)
    store.initialize()
    tasks = store.tasks()
    situations = store.situations()
    assert {task.audience_ref for task in tasks} == {"legacy.task:task-0", "legacy.task:task-1"}
    assert {item["audience_ref"] for item in situations} == {
        "legacy.situation:situation-0",
        "legacy.situation:situation-1",
    }
    with store.connect() as connection:
        assert connection.execute("SELECT version FROM schema_meta").fetchone()[0] == _SCHEMA_VERSION
