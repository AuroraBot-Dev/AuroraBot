"""验证归档工具的引用校验、严格输出预算和只读行为。"""

import json

import pytest
from aurora_agent.tools import ToolExecutionError
from aurora_bot.event_archive import EventArchive
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import register_plugins
from aurora_core.json_data import encode_json
from aurora_world import RECORDS, WorldRecords
from aurora_world.plugin import plugin


@pytest.fixture
def world():
    registry = bootstrap()
    register_plugins(registry, [plugin()])
    ctx = Context(registry)
    clock = [10000.0]
    records = WorldRecords(ctx, now=lambda: clock[0])
    records.open()
    try:
        yield ctx, records, clock
    finally:
        records.close()
        ctx.close()


def reference(record):
    return {"journal_id": record.position.journal_id, "record_id": record.record_id}


@pytest.mark.parametrize("budget", [1024, 2400, 8000])
def test_expired_event_is_read_in_bounded_pages_without_decoding_full_payload(world, monkeypatch, budget):
    ctx, records, clock = world
    payload = {"text": '文😀\x00\n"\\' * 700, "complete": False}
    record = records.append(source_id="sensor", message_id="one", payload=payload).record
    clock[0] += 7200
    records.refresh()
    assert ctx.get(RECORDS)["records"] == []
    before = ctx.snapshot()

    def forbidden_decode(value):
        raise AssertionError("分页不得先反序列化完整归档")

    monkeypatch.setattr("aurora_world.records.decode_json", forbidden_decode)
    archive = EventArchive(records, max_chars=budget)
    pages, offset = [], 0
    while True:
        result = archive.read({**reference(record), "offset": offset})
        assert len(encode_json(result)) <= budget
        assert result["format"] == "json" and result["source_id"] == "sensor" and result["received_at"] == 10000
        assert result["offset"] == offset and result["record_id"] == record.record_id
        pages.append(result["text"])
        if result["next_offset"] is None:
            break
        assert result["next_offset"] > offset
        offset = result["next_offset"]
    assert len(pages) > 1 and json.loads("".join(pages)) == payload
    assert ctx.snapshot() == before


@pytest.mark.parametrize(
    "change,code",
    [
        ({"journal_id": "wrong"}, "archive_wrong_journal"),
        ({"record_id": "missing"}, "archive_not_found"),
        ({"offset": 9000}, "archive_invalid_offset"),
    ],
)
def test_reference_errors_are_distinct_and_do_not_change_state(world, change, code):
    ctx, records, _ = world
    record = records.append(source_id="sensor", message_id="one", payload="原文").record
    before = ctx.snapshot()
    with pytest.raises(ToolExecutionError) as failure:
        EventArchive(records).read({**reference(record), **change})
    assert failure.value.code == code and ctx.snapshot() == before


def test_oversized_metadata_is_rejected_without_truncating_identity(world):
    _, records, _ = world
    record = records.append(source_id="s" * 5000, message_id="one", payload="原文").record
    with pytest.raises(ToolExecutionError) as failure:
        EventArchive(records, max_chars=1024).read(reference(record))
    assert failure.value.code == "archive_metadata_too_large"
    assert records.get_by_id(record.record_id) == record


def test_closed_archive_and_invalid_arguments_are_explicit(world):
    _, records, _ = world
    record = records.append(source_id="sensor", message_id="one", payload="原文").record
    archive = EventArchive(records)
    for extra in ({"offset": True}, {"offset": -1}, {"database": "foreign"}, {"journal_id": " "}):
        with pytest.raises(ValueError):
            archive.read({**reference(record), **extra})
    records.close()
    with pytest.raises(ToolExecutionError) as failure:
        archive.read(reference(record))
    assert failure.value.code == "archive_unavailable"
