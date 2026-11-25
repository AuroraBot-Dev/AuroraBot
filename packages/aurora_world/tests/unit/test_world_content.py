"""验证按数据库与记录身份读取原始 JSON 分页，不消费事件或修改视图。"""

import json

import pytest
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import register_plugins
from aurora_world import CursorError, WorldRecords
from aurora_world.plugin import plugin


@pytest.fixture
def world():
    registry = bootstrap()
    register_plugins(registry, [plugin()])
    ctx = Context(registry)
    records = WorldRecords(ctx, now=lambda: 10000.0)
    records.select("weather", "weather")
    records.open()
    try:
        yield ctx, records
    finally:
        records.close()
        ctx.close()


@pytest.mark.parametrize("payload", ['文😀\x00\n"\\' * 20, {"values": [False, None, 1.5, "中文"]}, [], None, 12])
def test_content_pages_reassemble_exact_payload_without_changing_state(world, payload):
    ctx, records = world
    record = records.append(source_id="sensor", message_id="one", payload=payload).record
    before = ctx.snapshot()
    text, offset = "", 0
    while True:
        page = records.read_content(
            journal_id=record.position.journal_id, record_id=record.record_id, offset=offset, limit=3
        )
        assert page.position == record.position and page.received_at == 10000
        assert page.source_id == "sensor" and page.message_id == "one"
        assert page.offset == offset and len(page.text) <= 3
        text += page.text
        if page.next_offset is None:
            break
        assert page.next_offset > offset
        offset = page.next_offset
    assert json.loads(text) == payload and len(text) == page.total_chars
    end = records.read_content(journal_id=record.position.journal_id, record_id=record.record_id, offset=len(text))
    assert end.text == "" and end.next_offset is None
    assert ctx.snapshot() == before and records.read() == (record,)


def test_reference_failures_do_not_fall_back_to_other_records(world):
    ctx, records = world
    record = records.append(source_id="sensor", message_id="one", payload="原文").record
    weather = records.append(source_id="weather", message_id="one", payload="观察").record
    before = ctx.snapshot()
    with pytest.raises(CursorError):
        records.read_content(journal_id="wrong", record_id=record.record_id)
    with pytest.raises(KeyError):
        records.read_content(journal_id=record.position.journal_id, record_id="missing")
    with pytest.raises(KeyError):
        records.read_content(journal_id=record.position.journal_id, record_id=weather.record_id)
    with pytest.raises(ValueError, match="超出"):
        records.read_content(journal_id=record.position.journal_id, record_id=record.record_id, offset=999)
    assert ctx.snapshot() == before


@pytest.mark.parametrize("change", [{"offset": -1}, {"offset": 2**63}, {"limit": 65537}])
def test_invalid_content_ranges_are_rejected(world, change):
    _, records = world
    record = records.append(source_id="sensor", message_id="one", payload="原文").record
    with pytest.raises(ValueError):
        records.read_content(journal_id=record.position.journal_id, record_id=record.record_id, **change)
