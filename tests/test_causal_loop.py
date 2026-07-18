from __future__ import annotations

import asyncio
from pathlib import Path

from src.contracts.amp import AmpEnvelope, new_amp
from src.localhost.runtime import AuroraRuntime


def test_amp_creates_task_agent_and_causal_fact(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        try:
            amp = new_amp(
                event_type="message.received",
                session_id="session",
                summary="hello",
                data={},
                source_app="test",
                source_instance="test",
            )
            await runtime.kernel.submit_amp(amp)
            result = await runtime.kernel.pump(1)
            task = runtime.kernel.get_task(result.ingested_task_ids[0])
            assert task is not None
            detail = runtime.kernel.task_detail(task.task_id)
            assert detail is not None
            assert detail["agents"][0]["parent_agent_id"] is None
            assert detail["events"][0]["type"] == "task.started"
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_replayed_amp_does_not_create_second_task(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        try:
            amp = new_amp(
                event_type="message.received",
                session_id="session",
                summary="hello",
                data={},
                source_app="test",
                source_instance="test",
            )
            await runtime.kernel.submit_amp(amp)
            await runtime.kernel.pump(1)
            await runtime.kernel.submit_amp(amp)
            await runtime.kernel.pump(1)
            assert len(runtime.kernel.tasks()) == 1
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_invalid_inbox_json_is_archived_without_task(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        invalid = runtime.configuration.runtime.workspace / "inbox" / "invalid.json"
        invalid.parent.mkdir(parents=True, exist_ok=True)
        invalid.write_text("{", encoding="utf-8")
        try:
            await runtime.kernel.pump()
            assert not runtime.kernel.tasks()
            assert (
                runtime.configuration.runtime.workspace / "archive" / "inbox" / "rejected" / "invalid.json"
            ).exists()
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_effect_receipt_without_owner_becomes_ambient_situation(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        receipt = new_amp(
            event_type="effect.succeeded",
            session_id="session",
            summary="orphan",
            data={"request_id": "missing", "capability": "missing", "result": {}},
            source_app="platform.test",
            source_instance="test",
        )
        try:
            await runtime.kernel.submit_amp(AmpEnvelope.parse(receipt.to_dict()))
            await runtime.kernel.pump()
            assert runtime.kernel.brain_context().ambient_situations[0]["summary"] == "orphan"
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
