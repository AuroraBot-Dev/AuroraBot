from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

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


def test_arbitrary_ambient_data_is_accepted(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        arbitrary = new_amp(
            event_type="message.received",
            session_id="bad",
            summary="arbitrary ambient fact",
            data={
                "ambient": True,
                "vendor_metadata": {"arbitrary": True},
            },
            source_app="test.chat",
            source_instance="test",
        )
        valid = new_amp(
            event_type="clock.changed",
            session_id="clock",
            summary="valid ambient fact",
            data={"ambient": True},
            source_app="clock",
            source_instance="test",
        )
        try:
            await runtime.kernel.submit_amp(arbitrary)
            await runtime.kernel.submit_amp(valid)
            runtime.kernel.ingest_ready()
            accepted = (
                runtime.configuration.runtime.workspace
                / "archive"
                / "inbox"
                / "accepted"
                / f"{arbitrary.header.message_id}.json"
            )
            assert accepted.exists()
            assert {item["summary"] for item in runtime.kernel.store.situations()} == {
                "arbitrary ambient fact",
                "valid ambient fact",
            }
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_external_tool_receipts_are_reserved(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        receipt = new_amp(
            event_type="tool.succeeded",
            session_id="session",
            summary="orphan",
            data={"request_id": "missing", "capability": "missing", "result": {}},
            source_app="platform.test",
            source_instance="test",
        )
        try:
            with pytest.raises(ValueError, match="reserved internal event type"):
                await runtime.submit_amp(receipt.to_dict())
            await runtime.kernel.submit_amp(AmpEnvelope.parse(receipt.to_dict()))
            await runtime.kernel.pump()
            rejected = project_root / "data/kernel/archive/inbox/rejected" / f"{receipt.header.message_id}.json"
            assert rejected.exists()
            assert not runtime.kernel.store.situations()
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
