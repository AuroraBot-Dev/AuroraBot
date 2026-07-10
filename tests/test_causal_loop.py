from __future__ import annotations

from pathlib import Path

from src.localhost.runtime import AuroraRuntime
from tests.test_events import valid_amp


def test_message_effect_and_receipt_form_auditable_two_cycle_loop(project_root: Path) -> None:
    runtime = AuroraRuntime.create(project_root)
    runtime.submit_amp(valid_amp())

    first = runtime.run_cycle()
    assert len(first["ingested_record_ids"]) == 1
    assert len(first["scheduled_record_ids"]) == 1
    assert first["platform_receipts_emitted"] == 1

    records = runtime.kernel._records()
    effect = next(record for record in records if record.amp["payload"]["type"] == "effect.requested")
    assert effect.amp["payload"]["data"]["capability"] == "debug.echo"
    assert effect.amp["payload"]["data"]["request_id"]

    second = runtime.run_cycle()
    assert len(second["ingested_record_ids"]) == 1
    receipt = runtime.kernel.get_record(second["ingested_record_ids"][0])
    assert receipt is not None
    assert receipt.parent_record_id == effect.record_id
    assert receipt.episode_id == effect.episode_id


def test_replayed_amp_does_not_create_a_second_effect(project_root: Path) -> None:
    runtime = AuroraRuntime.create(project_root)
    amp = valid_amp()
    runtime.submit_amp(amp)
    runtime.run_cycle()
    runtime.run_cycle()
    runtime.submit_amp(amp)
    replay = runtime.run_cycle()

    assert not replay["ingested_record_ids"]
    effects = [record for record in runtime.kernel._records() if record.amp["payload"]["type"] == "effect.requested"]
    assert len(effects) == 1


def test_invalid_inbox_json_is_preserved_as_an_error_record(project_root: Path) -> None:
    runtime = AuroraRuntime.create(project_root)
    (runtime.configuration.runtime.workspace / "inbox" / "broken.json").write_text("not json", encoding="utf-8")

    result = runtime.run_cycle()

    errors = [
        record
        for record in runtime.kernel._records()
        if record.amp["payload"]["type"] == "system.ingress_rejected"
    ]
    assert not result["ingested_record_ids"]
    assert len(errors) == 1
    assert errors[0].status == "ERROR"
