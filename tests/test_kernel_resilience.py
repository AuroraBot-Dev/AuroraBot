from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from src.kernel.contracts import (
    ActivityStatus,
    AgentContext,
    AgentDecision,
    AgentLimits,
    AgentProfile,
    Completion,
    KernelConfiguration,
    TaskBudget,
)
from src.kernel.events import AmpEnvelope, new_amp
from src.kernel.runtime import AgentKernel

if TYPE_CHECKING:
    from pathlib import Path


class ModelHandler:
    def handle(self, context: AgentContext) -> AgentDecision:
        if context.message.type == "model.failed":
            return AgentDecision(completion=Completion(str(context.message.payload["error"]), silent=True))
        return AgentDecision(model_request={"role": "fast", "messages": []})


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
