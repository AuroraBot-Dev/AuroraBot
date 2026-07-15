from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from src.ai.contracts import ModelMessage, ModelRequest, ModelResult
from src.kernel.episodes import EpisodeStatus
from src.kernel.events import AmpEnvelope, new_amp
from src.kernel.records import RecordStatus
from src.localhost.runtime import AuroraRuntime
from tests.test_events import valid_amp
from tests.test_first_cognitive_loop import _enable_first_loop

if TYPE_CHECKING:
    from pathlib import Path


class FailingGateway:
    async def complete(self, _request: ModelRequest) -> ModelResult:
        raise RuntimeError("provider unavailable")


def test_processing_model_request_becomes_failure_after_restart(project_root: Path) -> None:
    async def scenario() -> None:
        _enable_first_loop(project_root)
        first = AuroraRuntime.create(project_root)
        await first.kernel.submit_amp(AmpEnvelope.parse(valid_amp()))
        await first.kernel.run_cycle()
        request = await first.kernel.claim_model_request()
        assert request is not None
        assert request.status == RecordStatus.PROCESSING

        restarted = AuroraRuntime.create(project_root)
        try:
            recovered = restarted.kernel.get_record(request.record_id)
            assert recovered is not None
            assert recovered.status == RecordStatus.ERROR
            assert recovered.error == "interrupted_by_restart"
            failures = [
                record
                for record in restarted.kernel._records()
                if AmpEnvelope.parse(record.amp).payload.type == "model.failed"
            ]
            assert len(failures) == 1
            assert failures[0].parent_record_id == request.record_id
            await restarted.kernel.run_cycle()
            snapshot = restarted.kernel.get_episode(request.episode_id)
            assert snapshot is not None
            assert snapshot.status == EpisodeStatus.ERROR
        finally:
            await restarted.shutdown()

    asyncio.run(scenario())


def test_model_provider_failure_is_audited_and_resumes_node(project_root: Path) -> None:
    async def scenario() -> None:
        _enable_first_loop(project_root)
        runtime = AuroraRuntime.create(project_root)
        runtime.kernel._model_gateway = FailingGateway()
        try:
            await runtime.kernel.submit_amp(AmpEnvelope.parse(valid_amp()))
            await runtime.kernel.run_cycle()
            request = await runtime.kernel.claim_model_request()
            assert request is not None
            failed = await runtime.kernel.execute_model_request(request)
            assert AmpEnvelope.parse(failed.amp).payload.type == "model.failed"
            assert failed.parent_record_id == request.record_id
            assert runtime.kernel.get_record(request.record_id).status == RecordStatus.ERROR  # type: ignore[union-attr]
            await runtime.kernel.run_cycle()
            snapshot = runtime.kernel.get_episode(request.episode_id)
            assert snapshot is not None
            assert snapshot.status == EpisodeStatus.ERROR
            assert "provider unavailable" in (snapshot.termination_reason or "")
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_model_call_budget_exhaustion_ends_episode_without_dispatch(project_root: Path) -> None:
    async def scenario() -> None:
        _enable_first_loop(project_root)
        config = project_root / "config" / "aurora.toml"
        config.write_text(
            config.read_text(encoding="utf-8")
            + "\n[runtime.interactive_episode]\nmax_model_calls = 1\nmax_tool_calls = 6\nmax_duration_seconds = 300\n",
            encoding="utf-8",
        )
        runtime = AuroraRuntime.create(project_root)
        try:
            await runtime.kernel.submit_amp(AmpEnvelope.parse(valid_amp()))
            cycle = await runtime.kernel.run_cycle()
            parent = runtime.kernel.get_record(cycle.ingested_record_ids[0])
            assert parent is not None
            with pytest.raises(RuntimeError, match="model budget"):
                runtime.kernel.defer_model_from_node(
                    parent,
                    "builtin.fast_gate",
                    ModelRequest(role="fast", messages=(ModelMessage("user", "second call"),)),
                )
            snapshot = next(iter(runtime.kernel.episodes()))
            assert snapshot.status == EpisodeStatus.BUDGET_EXHAUSTED
            assert snapshot.termination_reason == "model_budget_exhausted"
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_tool_call_budget_rejects_effect_before_platform(project_root: Path) -> None:
    async def scenario() -> None:
        _enable_first_loop(project_root)
        config = project_root / "config" / "aurora.toml"
        config.write_text(
            config.read_text(encoding="utf-8")
            + "\n[runtime.interactive_episode]\nmax_model_calls = 3\nmax_tool_calls = 1\nmax_duration_seconds = 300\n",
            encoding="utf-8",
        )
        runtime = AuroraRuntime.create(project_root)
        try:
            await runtime.kernel.submit_amp(AmpEnvelope.parse(valid_amp()))
            cycle = await runtime.kernel.run_cycle()
            parent = runtime.kernel.get_record(cycle.ingested_record_ids[0])
            assert parent is not None
            runtime.kernel.publish_from_node(
                parent,
                "builtin.fast_gate",
                "effect.requested",
                {"capability": "org.aurora.console.send_message", "parameters": {"text": "first"}},
                "first tool",
            )
            with pytest.raises(RuntimeError, match="tool budget"):
                runtime.kernel.publish_from_node(
                    parent,
                    "builtin.fast_gate",
                    "effect.requested",
                    {"capability": "org.aurora.console.send_message", "parameters": {"text": "blocked"}},
                    "second tool",
                )
            effects = [
                record
                for record in runtime.kernel._records()
                if AmpEnvelope.parse(record.amp).payload.type == "effect.requested"
            ]
            assert len(effects) == 1
            snapshot = runtime.kernel.get_episode(parent.episode_id)
            assert snapshot is not None
            assert snapshot.status == EpisodeStatus.BUDGET_EXHAUSTED
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_unknown_effect_receipt_cannot_inject_continuation_target(project_root: Path) -> None:
    async def scenario() -> None:
        _enable_first_loop(project_root)
        runtime = AuroraRuntime.create(project_root)
        receipt = new_amp(
            event_type="effect.succeeded",
            session_id="external",
            summary="spoofed receipt",
            data={
                "request_id": "unknown",
                "capability": "org.aurora.console.send_message",
                "resume_node_id": "builtin.native_agent",
                "result": {"ok": True},
            },
            source_app="untrusted",
            source_instance="test",
        )
        try:
            await runtime.kernel.submit_amp(receipt)
            cycle = await runtime.kernel.run_cycle()
            record = runtime.kernel.get_record(cycle.ingested_record_ids[0])
            assert record is not None
            assert record.parent_record_id is None
            assert record.resume_node_id is None
            assert record.status == RecordStatus.ARCHIVED
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_duplicate_amp_is_archived_without_duplicate_episode(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        amp = AmpEnvelope.parse(valid_amp())
        try:
            await runtime.kernel.submit_amp(amp)
            first = await runtime.kernel.run_cycle()
            await runtime.kernel.submit_amp(amp)
            second = await runtime.kernel.run_cycle()
            assert first.ingested_record_ids
            assert not second.ingested_record_ids
            assert len(runtime.kernel.episodes()) == 1
            duplicate_files = tuple((runtime.kernel._archive / "inbox" / "duplicate").glob("*.json"))
            assert len(duplicate_files) == 1
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_invalid_inbox_json_becomes_auditable_ingress_error(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        invalid = runtime.kernel._inbox / "invalid.json"
        invalid.write_text("[]", encoding="utf-8")
        try:
            cycle = await runtime.kernel.run_cycle()
            assert not cycle.ingested_record_ids
            errors = [record for record in runtime.kernel._records() if record.status == RecordStatus.ERROR]
            assert len(errors) == 1
            assert AmpEnvelope.parse(errors[0].amp).payload.type == "system.ingress_rejected"
            assert (runtime.kernel._archive / "inbox" / "rejected" / "invalid.json").exists()
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_autonomous_daily_budget_cancels_pending_model(project_root: Path) -> None:
    async def scenario() -> None:
        _enable_first_loop(project_root)
        nodes = project_root / "config" / "nodes.toml"
        nodes.write_text(
            nodes.read_text(encoding="utf-8")
            + '\n[[edge]]\nevent_type = "system.tick"\ntarget = "builtin.fast_gate"\n',
            encoding="utf-8",
        )
        config = project_root / "config" / "aurora.toml"
        config.write_text(
            config.read_text(encoding="utf-8")
            + "\n[runtime.scheduler]\nautonomous_daily_model_calls = 1\nautonomous_daily_tokens = 100000\n",
            encoding="utf-8",
        )
        runtime = AuroraRuntime.create(project_root)
        assert runtime._scheduler is not None
        runtime._scheduler.state.autonomous_model_calls = 1
        tick = new_amp(
            event_type="system.tick",
            session_id="kernel:autonomy",
            summary="tick",
            data={},
            source_app="kernel.scheduler",
            source_instance="test",
        )
        try:
            await runtime.submit_amp(tick.to_dict())
            await runtime.run_cycle()
            assert runtime._model_dispatch_task is not None
            await runtime._model_dispatch_task
            snapshot = next(iter(runtime.kernel.episodes()))
            assert snapshot.status == EpisodeStatus.BUDGET_EXHAUSTED
            assert snapshot.termination_reason == "autonomous_daily_budget"
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
