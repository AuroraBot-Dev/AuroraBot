"""验证近期呈现预算与事件归档、去重和消费位置相互独立。"""

import asyncio
import sqlite3
from dataclasses import replace

import pytest
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, ContextSnapshot, StateAddress, StateRecord
from aurora_core.discovery import register_plugins
from aurora_core.storage import StorageService
from aurora_world import ENVIRONMENT, RECORDS, CursorError, MessageConflictError, WorldPosition, WorldRecords, WorldView
from aurora_world.migrate import migrate
from aurora_world.plugin import plugin


def context():
    registry = bootstrap()
    register_plugins(registry, [plugin()])
    return Context(registry)


@pytest.fixture
def world(tmp_path):
    clock = [10000.0]
    ctx = context()
    with StorageService(tmp_path) as storage:
        records = WorldRecords(ctx, storage, now=lambda: clock[0])
        records.configure(view=WorldView(max_chars=600, max_event_chars=200))
        records.open()
        try:
            yield ctx, records, clock, storage
        finally:
            records.close()
            ctx.close()


def test_whole_object_budget_preserves_history_deduplication_and_cursor(world):
    ctx, records, clock, _ = world
    original = [records.append(source_id="chat", message_id=str(i), payload="文" * 150).record for i in range(20)]
    items = ctx.get(RECORDS)["records"]
    assert 1 < len(items) < len(original)
    assert all(item["text"] == "文" * 150 and not item["abridged"] for item in items)
    assert [item["record_id"] for item in items] == [item.record_id for item in original[-len(items) :]]
    assert records.read(after=original[0].position) == tuple(original[1:])
    assert records.append(source_id="chat", message_id="0", payload="文" * 150).duplicate
    with pytest.raises(MessageConflictError):
        records.append(source_id="chat", message_id="0", payload="冲突")
    clock[0] += 3600
    records.refresh()
    assert ctx.get(RECORDS)["records"] == []
    assert records.read() == tuple(original)
    assert records.append(source_id="chat", message_id="0", payload="文" * 150).duplicate
    assert ctx.get(RECORDS)["records"] == []


def test_oversized_event_keeps_original_and_explicit_preview(world):
    ctx, records, _, _ = world
    payload = {"text": "长内容" * 10000}
    receipt = records.append(source_id="chat", message_id="large", payload=payload)
    item = ctx.get(RECORDS)["records"][0]
    assert item["abridged"] and len(item["text"]) < 300
    assert item["record_id"] == receipt.record.record_id
    assert records.get(source_id="chat", message_id="large").payload == payload
    assert records.get_by_id(item["record_id"]).payload == payload


def test_environment_is_bounded_without_advancing_event_journal(world):
    ctx, records, clock, _ = world
    records.select("clock", "time")
    records.select("weather", "weather")
    event = records.append(source_id="chat", message_id="1", payload="事件").record
    for index in range(6):
        records.append(source_id="clock", message_id=str(index), payload={"time": index})
        records.append(source_id="weather", message_id=str(index), payload={"temperature": index})
        clock[0] += 1
    assert len(records.observations(source_id="clock")) == 1
    assert len(records.observations(source_id="weather")) == 4
    assert records.read() == (event,)
    assert records.read(after=event.position) == ()
    clock[0] += 3600
    records.refresh()
    assert [item.payload for item in records.observations(source_id="weather")] == [{"temperature": 5}]
    assert len(ctx.list(key=ENVIRONMENT)) == 2
    assert records.observations(source_id="clock")[0].payload == {"time": 5}


def test_idle_refresh_expires_view_and_stops_cleanly(world):
    async def scenario():
        ctx, records, clock, _ = world
        records.view = replace(records.view, refresh_seconds=0.01)
        records.append(source_id="chat", message_id="1", payload="过期")
        records.start()
        clock[0] += 3600
        try:
            async with asyncio.timeout(1):
                while ctx.get(RECORDS)["records"]:
                    await asyncio.sleep(0.01)
        finally:
            await records.stop()
        assert records._worker is None
        assert len(records.read()) == 1

    asyncio.run(scenario())


def test_database_failure_does_not_publish_or_consume_sequence(world):
    ctx, records, _, _ = world
    db = records._connection()
    db.execute("CREATE TRIGGER reject_insert BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, '拒绝写入'); END")
    before = ctx.snapshot()
    with pytest.raises(sqlite3.IntegrityError):
        records.append(source_id="chat", message_id="1", payload="原文")
    assert ctx.snapshot() == before and records.read() == ()
    db.execute("DROP TRIGGER reject_insert")
    assert records.append(source_id="chat", message_id="1", payload="原文").record.position.sequence == 1


def test_refresh_failure_retries_without_replaying_events(world, monkeypatch, caplog):
    async def scenario():
        ctx, records, clock, _ = world
        records.view = replace(records.view, refresh_seconds=0.01)
        receipt = records.append(source_id="chat", message_id="1", payload="原文")
        clock[0] += 3600
        refresh = records.refresh

        def fail():
            raise OSError("不可记录的详情")

        monkeypatch.setattr(records, "refresh", fail)
        records.start()
        with pytest.raises(RuntimeError, match="已经启动"):
            records.start()
        try:
            async with asyncio.timeout(1):
                while records.last_error is None:
                    await asyncio.sleep(0.01)
                monkeypatch.setattr(records, "refresh", refresh)
                while records.last_error is not None:
                    await asyncio.sleep(0.01)
            assert ctx.get(RECORDS)["records"] == []
            assert records.read() == (receipt.record,)
            assert "presentation_failed" in caplog.text and "不可记录的详情" not in caplog.text
        finally:
            await records.stop()

    asyncio.run(scenario())


def test_migration_retries_after_snapshot_failure_without_reinserting_events(tmp_path, monkeypatch):
    from aurora_core.snapshots import JsonSnapshotStore

    old = {
        "version": 1,
        "journal_id": "legacy",
        "records": [{"sequence": 1, "record_id": "r1", "source_id": "chat", "message_id": "m1", "payload": "原文"}],
    }
    with StorageService(tmp_path) as storage:
        store = storage.snapshot_store()
        store.save(ContextSnapshot(0, (StateRecord(StateAddress(RECORDS), old),)))
        original = store.path.read_bytes()
    save = JsonSnapshotStore.save

    def fail(*args):
        raise OSError("快照失败")

    monkeypatch.setattr(JsonSnapshotStore, "save", fail)
    with pytest.raises(OSError, match="快照失败"):
        migrate(tmp_path)
    assert store.path.read_bytes() == original
    monkeypatch.setattr(JsonSnapshotStore, "save", save)
    assert migrate(tmp_path) == 1
    with sqlite3.connect(tmp_path / "namespaces/ns-org.aurora.world/events.sqlite3") as db:
        assert db.execute("SELECT sequence, record_id FROM events").fetchall() == [(1, "r1")]


@pytest.mark.parametrize(
    "damage",
    [
        {"next_sequence": True},
        {"pruned_through": -1},
        {"pruned_record_id": None},
        {"pruned_record_id": "r3"},
        {"records": []},
        {"version": 99},
    ],
)
def test_migration_rejects_corrupt_legacy_boundaries_without_overwriting_snapshot(tmp_path, damage):
    old = {
        "version": 2,
        "journal_id": "legacy",
        "next_sequence": 4,
        "pruned_through": 2,
        "pruned_record_id": "r2",
        "records": [{"sequence": 3, "record_id": "r3", "source_id": "chat", "message_id": "m3", "payload": "原文"}],
        **damage,
    }
    with StorageService(tmp_path) as storage:
        store = storage.snapshot_store()
        store.save(ContextSnapshot(0, (StateRecord(StateAddress(RECORDS), old),)))
        original = store.path.read_bytes()
    with pytest.raises(ValueError):
        migrate(tmp_path)
    assert store.path.read_bytes() == original
    assert not (tmp_path / "namespaces/ns-org.aurora.world/events.sqlite3").exists()


def test_committed_event_recovers_without_ctx_flush(world):
    _, records, clock, storage = world
    receipt = records.append(source_id="chat", message_id="1", payload="已提交")
    records.close()
    restored = context()
    other = WorldRecords(restored, storage, now=lambda: clock[0])
    try:
        other.open()
        assert other.read() == (receipt.record,)
        assert other.append(source_id="chat", message_id="1", payload="已提交").duplicate
        assert other.append(source_id="chat", message_id="2", payload="新输入").record.position.sequence == 2
    finally:
        other.close()
        restored.close()


def test_snapshot_from_different_database_is_rejected(world, tmp_path):
    ctx, records, _, _ = world
    records.append(source_id="chat", message_id="1", payload="原文")
    restored = context()
    restored.restore(ctx.snapshot().records)
    with StorageService(tmp_path / "other") as storage:
        other = WorldRecords(restored, storage)
        try:
            with pytest.raises(CursorError):
                other.open()
        finally:
            other.close()
            restored.close()


@pytest.mark.parametrize("version", [1, 2])
def test_explicit_migration_preserves_identity_backup_and_legacy_gaps(tmp_path, version):
    old = {
        "version": version,
        "journal_id": "legacy",
        "records": [
            {
                "sequence": 1 if version == 1 else 3,
                "record_id": "r3",
                "source_id": "chat",
                "message_id": "m3",
                "payload": {"text": "原文"},
            }
        ],
    }
    if version == 2:
        old.update(next_sequence=4, pruned_through=2, pruned_record_id="r2")
    with StorageService(tmp_path) as storage:
        store = storage.snapshot_store()
        store.save(ContextSnapshot(0, (StateRecord(StateAddress(RECORDS), old),)))
        original = store.path.read_bytes()
        ctx = context()
        ctx.restore(store.load())
        records = WorldRecords(ctx, storage)
        with pytest.raises(ValueError, match="显式迁移"):
            records.open()
        assert store.path.read_bytes() == original
        records.close()
        ctx.close()
    assert migrate(tmp_path) == 1
    assert migrate(tmp_path) == 0
    assert (tmp_path / "framework/ctx.before-world-database.json").read_bytes() == original
    with StorageService(tmp_path) as storage:
        ctx = context()
        ctx.restore(storage.snapshot_store().load())
        records = WorldRecords(ctx, storage)
        try:
            records.open()
            first = records.read()[0]
            assert first.record_id == "r3" and first.position.journal_id == "legacy"
            assert records.append(source_id="chat", message_id="m3", payload={"text": "原文"}).duplicate
            if version == 2:
                with pytest.raises(CursorError):
                    records.read(after=WorldPosition("legacy", 1, "r1"))
                assert records.read(after=WorldPosition("legacy", 2, "r2")) == (first,)
            assert (
                records.append(source_id="chat", message_id="new", payload=None).record.position.sequence
                == first.position.sequence + 1
            )
        finally:
            records.close()
            ctx.close()


@pytest.mark.parametrize(
    "values",
    [
        {"max_chars": 0},
        {"max_event_chars": True},
        {"recent_seconds": float("nan")},
        {"refresh_seconds": 0},
        {"time_count": 0},
    ],
)
def test_invalid_view_limits_are_rejected(values):
    with pytest.raises(ValueError):
        WorldView(**values)
