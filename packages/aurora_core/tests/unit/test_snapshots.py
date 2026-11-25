"""验证完整快照、恢复校验及文件替换失败行为。"""

import pytest
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateAddress, StateKey, StateRecord
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry
from aurora_core.snapshots import JsonSnapshotStore

CONFIG = Id("dev.example:state/config")
OTHER = Id("dev.other:state/data")


def make_context() -> Context:
    registry = bootstrap()
    for key in (CONFIG, OTHER):
        registry.register(RegistryEntry(key, "state_key", StateKey(), "测试插件"))
    return Context(registry)


def test_all_state_roundtrips_with_locations_and_deletions(tmp_path):
    ctx = make_context()
    ctx.set(CONFIG, {"中文": [None, True, 1, 1.5]})
    ctx.set(CONFIG, "会话", location={"session_id": "s1"})
    ctx.set(OTHER, "删除项")
    ctx.delete(OTHER)
    snapshot = ctx.snapshot()
    ctx.set(CONFIG, "捕获后的修改")
    store = JsonSnapshotStore(tmp_path / "nested" / "state.json")
    store.save(snapshot)
    restored = make_context()
    changes = []
    restored.subscribe(changes.append)
    restored.restore(store.load())
    assert restored.get(CONFIG) == {"中文": [None, True, 1, 1.5]}
    assert restored.get(CONFIG, location={"session_id": "s1"}) == "会话"
    assert len(restored.list()) == 2
    assert changes == []


def test_snapshot_does_not_share_mutable_values():
    ctx = make_context()
    ctx.set(CONFIG, [1])
    snapshot = ctx.snapshot()
    value = snapshot.records[0].value
    assert isinstance(value, list)
    value.append(2)
    assert ctx.get(CONFIG) == [1]


def test_restore_unknown_definition_is_atomic():
    ctx = make_context()
    records = (StateRecord(StateAddress(CONFIG), 1), StateRecord(StateAddress(Id("dev.missing:state/data")), 2))
    with pytest.raises(KeyError):
        ctx.restore(records)
    assert ctx.list() == ()


def test_restore_validation_failure_is_atomic():
    def validate(value: object) -> None:
        if not isinstance(value, int):
            raise TypeError("需要整数")

    registry = bootstrap()
    registry.register(RegistryEntry(CONFIG, "state_key", StateKey(validate), "测试插件"))
    ctx = Context(registry)
    records = (StateRecord(StateAddress(CONFIG), 1), StateRecord(StateAddress(CONFIG, (("session_id", "s1"),)), "无效"))
    with pytest.raises(TypeError, match="需要整数"):
        ctx.restore(records)
    assert ctx.list() == ()


def test_restore_rejects_duplicates_and_existing_work():
    ctx = make_context()
    record = StateRecord(StateAddress(CONFIG), 1)
    with pytest.raises(ValueError, match="重复"):
        ctx.restore((record, record))
    assert ctx.list() == ()
    ctx.set(CONFIG, 2)
    ctx.delete(CONFIG)
    with pytest.raises(RuntimeError, match="首次写入前"):
        ctx.restore((record,))


def test_successful_empty_restore_cannot_be_repeated():
    ctx = make_context()
    ctx.restore(())
    with pytest.raises(RuntimeError, match="首次写入前"):
        ctx.restore((StateRecord(StateAddress(CONFIG), "不得再次恢复"),))
    assert ctx.list() == ()


@pytest.mark.parametrize("value", [object(), (1, 2), {1: "非字符串键"}, float("nan"), float("inf")])
def test_non_json_state_does_not_overwrite_previous_snapshot(tmp_path, value):
    store = JsonSnapshotStore(tmp_path / "state.json")
    ctx = make_context()
    ctx.set(CONFIG, "有效")
    store.save(ctx.snapshot())
    previous = store.path.read_bytes()
    ctx.set(CONFIG, value)
    with pytest.raises((TypeError, ValueError)):
        store.save(ctx.snapshot())
    assert store.path.read_bytes() == previous


def test_cyclic_value_is_rejected(tmp_path):
    value = []
    value.append(value)
    ctx = make_context()
    ctx.set(CONFIG, value)
    with pytest.raises(ValueError, match="循环引用"):
        JsonSnapshotStore(tmp_path / "state.json").save(ctx.snapshot())


def test_replace_failure_keeps_previous_snapshot_and_cleans_temp(tmp_path, monkeypatch):
    store = JsonSnapshotStore(tmp_path / "state.json")
    ctx = make_context()
    ctx.set(CONFIG, "旧快照")
    store.save(ctx.snapshot())
    previous = store.path.read_bytes()

    def fail_replace(source, destination):
        raise OSError("替换失败")

    monkeypatch.setattr("aurora_core.snapshots.os.replace", fail_replace)
    ctx.set(CONFIG, "新快照")
    with pytest.raises(OSError, match="替换失败"):
        store.save(ctx.snapshot())
    assert store.path.read_bytes() == previous
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize(
    "content",
    [
        "{",
        '{"version":2,"entries":[]}',
        '{"version":1,"entries":{}}',
        '{"version":1,"version":1,"entries":[]}',
        '{"version":1,"entries":[{"id":"dev.example:state/config","location":{},"value":NaN}]}',
        '{"version":1,"entries":[{"id":"dev.example:state/config","location":{"session_id":1},"value":0}]}',
    ],
)
def test_corrupt_snapshot_is_reported_and_unchanged(tmp_path, content):
    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises((ValueError, TypeError)):
        JsonSnapshotStore(path).load()
    assert path.read_text(encoding="utf-8") == content


def test_missing_snapshot_is_empty(tmp_path):
    assert JsonSnapshotStore(tmp_path / "missing.json").load() == ()
