"""验证世界来源身份、重复接纳、位置读取与 ctx 通知的公共行为。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import cast

import pytest
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateAddress, StateRecord
from aurora_core.discovery import register_plugins
from aurora_world import RECORDS, CursorError, MessageConflictError, WorldPosition, WorldRecords
from aurora_world.plugin import plugin


@pytest.fixture
def world():
    registry = bootstrap()
    register_plugins(registry, [plugin()])
    ctx = Context(registry)
    records = WorldRecords(ctx)
    records.open()
    yield ctx, records
    records.close()
    ctx.close()


def test_discovery_and_construction_do_not_initialize_state_or_require_consumers(world):
    ctx, records = world
    assert plugin().requires == ()
    assert ctx.list() == () and records.read() == ()
    assert ctx.list() == ()
    with pytest.raises(KeyError):
        records.get(source_id="room-a", message_id="1")
    with pytest.raises(KeyError):
        WorldRecords(Context(bootstrap())).open()


def test_duplicate_identity_is_scoped_to_source_and_does_not_publish(world):
    ctx, records = world
    changes = []
    handle = ctx.subscribe(changes.append, key=RECORDS, location={})
    first = records.append(source_id="room-a", message_id="1", payload={"text": "你好", "extra": None})
    duplicate = records.append(source_id="room-a", message_id="1", payload={"extra": None, "text": "你好"})
    other = records.append(source_id="room-b", message_id="1", payload="你好")
    assert not first.duplicate and duplicate.duplicate and not other.duplicate
    assert first.record == duplicate.record == records.get(source_id="room-a", message_id="1")
    assert first.record.record_id != other.record.record_id
    assert first.record.position.journal_id == other.record.position.journal_id
    assert [change.revision for change in changes] == [1, 2]
    assert [record.position.sequence for record in records.read()] == [1, 2]
    assert ctx.unsubscribe(handle) and not ctx.unsubscribe(handle)
    records.append(source_id="room-a", message_id="2", payload=None)
    assert len(changes) == 2


@pytest.mark.parametrize("different", [False, 0.0, "0", None, [], {}])
def test_conflicting_content_preserves_record_and_revision(world, different):
    ctx, records = world
    first = records.append(source_id="source", message_id="1", payload=0)
    before = ctx.snapshot()
    with pytest.raises(MessageConflictError):
        records.append(source_id="source", message_id="1", payload=different)
    assert ctx.snapshot() == before
    assert records.read() == (first.record,)


def test_payloads_and_notifications_are_independent_copies(world):
    ctx, records = world
    observed = []
    ctx.subscribe(observed.append, key=RECORDS, location={})
    payload = {"nested": ["原文"]}
    receipt = records.append(source_id="source", message_id="1", payload=payload)
    payload["nested"].clear()
    receipt.record.payload["nested"].append("篡改回执")
    observed[0].value["records"][0]["text"] = "篡改呈现"
    item = records.read()[0]
    assert item.payload == {"nested": ["原文"]}
    item.payload["nested"].clear()
    assert records.get(source_id="source", message_id="1").payload == {"nested": ["原文"]}


def test_pagination_source_filter_and_positions_survive_new_facades(world):
    ctx, records = world
    for index, source in enumerate(("a", "b", "a", "b")):
        records.append(source_id=source, message_id=str(index), payload=index)
    first = records.read(limit=1)[0]
    assert [item.payload for item in records.read(after=first.position, limit=2)] == [1, 2]
    assert [item.position.sequence for item in records.read(after=first.position, source_id="b")] == [2, 4]
    last = records.read()[-1]
    assert records.read(after=last.position) == ()
    assert records.read(source_id="missing") == ()
    assert records.read(after=WorldPosition(first.position.journal_id, 0))[0] == first
    for position in (WorldPosition("another-journal", 0), WorldPosition(first.position.journal_id, 5, "missing")):
        with pytest.raises(CursorError):
            records.read(after=position)
    ctx.delete(RECORDS)
    assert records.read(after=first.position) == (records.read()[1:])
    replacement = records.append(source_id="a", message_id="0", payload=0)
    assert replacement.duplicate and replacement.record == first
    assert ctx.get(RECORDS)["records"]


def test_reentrant_subscribers_read_committed_records_and_keep_sequence_order(world, caplog):
    ctx, records = world
    received = []

    def append_during_notification(change):
        assert records.read()
        if change.value["records"][-1]["sequence"] == 1:
            records.append(source_id="b", message_id="1", payload="嵌套输入")
        raise RuntimeError("消费者失败")

    ctx.subscribe(append_during_notification, key=RECORDS, location={})
    ctx.subscribe(lambda change: received.append(change.value["records"][-1]["sequence"]), key=RECORDS, location={})
    first = records.append(source_id="a", message_id="1", payload="首条输入")
    assert first.record.position.sequence == 1
    assert received == [1, 2]
    assert len(records.read()) == 2 and "消费者失败" in caplog.text


def test_failed_presentation_keeps_durable_event_and_retry_repairs_view(world, monkeypatch):
    ctx, records = world
    records.append(source_id="source", message_id="1", payload="第一条")
    before = ctx.snapshot()
    original = ctx.set

    def fail(*args, **kwargs):
        raise OSError("提交失败")

    monkeypatch.setattr(ctx, "set", fail)
    with pytest.raises(OSError, match="提交失败"):
        records.append(source_id="source", message_id="2", payload="第二条")
    assert ctx.snapshot() == before
    monkeypatch.setattr(ctx, "set", original)
    second = records.append(source_id="source", message_id="2", payload="第二条")
    assert second.record.position.sequence == 2 and second.duplicate
    assert records.read()[-1] == second.record


@pytest.mark.parametrize("payload", [float("nan"), {1: "键"}, "\ud800"])
def test_invalid_json_does_not_initialize_the_journal(world, payload):
    ctx, records = world
    with pytest.raises((TypeError, ValueError)):
        records.append(source_id="source", message_id="1", payload=payload)
    assert ctx.list() == ()


@pytest.mark.parametrize("identity", ["  ", "\ud800"])
def test_invalid_identities_are_rejected_before_writing(world, identity):
    ctx, records = world
    for field in ("source_id", "message_id"):
        request = {"source_id": "source", "message_id": "1", "payload": None, field: identity}
        with pytest.raises((TypeError, ValueError)):
            records.append(**request)
    assert ctx.list() == ()


def test_invalid_positions_limits_and_cross_thread_access_are_rejected(world):
    ctx, records = world
    for sequence in (-1, True, 1.5):
        with pytest.raises(ValueError):
            WorldPosition("journal", cast(int, sequence))
    with pytest.raises(ValueError):
        WorldPosition("journal", 1)
    with pytest.raises(ValueError):
        WorldPosition("journal", 0, "unexpected")
    for limit in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            records.read(limit=limit)
    with pytest.raises(TypeError):
        records.read(after=1)
    with ThreadPoolExecutor(max_workers=1) as executor, pytest.raises(RuntimeError, match="线程"):
        executor.submit(records.append, source_id="source", message_id="1", payload=None).result()
    assert ctx.list() == ()


@pytest.mark.parametrize(
    "damage",
    [
        lambda data: data.update(version=99),
        lambda data: data.update(version=True),
        lambda data: data.update(journal_id=""),
        lambda data: data.update(records={}),
        lambda data: data.update(extra=None),
        lambda data: data["records"][0].update(sequence=True),
        lambda data: data["records"][0].update(sequence=2),
        lambda data: data["records"][0].update(source_id=""),
        lambda data: data["records"][0].pop("text"),
        lambda data: data["records"].append({**data["records"][0], "sequence": 2, "record_id": "other"}),
        lambda data: data["records"].append({**data["records"][0], "sequence": 2, "message_id": "other"}),
    ],
)
def test_corrupt_state_is_rejected_on_write_and_restore(world, damage):
    ctx, records = world
    records.append(source_id="source", message_id="1", payload=None)
    before = ctx.snapshot()
    data = deepcopy(ctx.get(RECORDS))
    damage(data)
    with pytest.raises((TypeError, ValueError)):
        ctx.set(RECORDS, data)
    assert ctx.snapshot() == before
    restored = Context(ctx.registry)
    try:
        with pytest.raises((TypeError, ValueError)):
            restored.restore((StateRecord(StateAddress(RECORDS, ()), data),))
        assert restored.list() == ()
    finally:
        restored.close()
