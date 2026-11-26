"""验证结构化数据读写、事务失败和连接释放。"""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from aurora_core.directories import DataDirectories
from aurora_core.storage import StorageService


def test_values_are_independent_and_survive_reopen(tmp_path):
    source = {"列表": [1], "old": True}
    with StorageService(tmp_path) as store:
        store.set("dev.example", "a", source)
        source["列表"].append(2)
        received = store.get("dev.example", "a")
        assert isinstance(received, dict)
        received["列表"].append(3)
        assert store.get("dev.example", "a") == {"列表": [1], "old": True}
        store.set("dev.example", "a", {"new": True})
        store.set("dev.other", "a", None)
    with StorageService(tmp_path) as store:
        assert store.get("dev.example", "a") == {"new": True}
        assert store.get("dev.other", "a") is None


def test_keys_missing_and_delete(tmp_path):
    with StorageService(tmp_path) as store:
        with pytest.raises(KeyError):
            store.get("dev.example", "missing")
        for key in ("z", "a", "a' OR 1=1 --"):
            store.set("dev.example", key, 1)
        assert store.keys("dev.example") == ("a", "a' OR 1=1 --", "z")
        assert store.keys("dev.other") == ()
        assert store.delete("dev.example", "a' OR 1=1 --") is True
        assert store.delete("dev.example", "a' OR 1=1 --") is False
        assert store.keys("dev.example") == ("a", "z")


@pytest.mark.parametrize("value", [object(), {1: "无效键"}, (1, 2), float("nan")])
def test_invalid_json_does_not_replace_committed_value(tmp_path, value):
    with StorageService(tmp_path) as store:
        store.set("dev.example", "key", "有效")
        with pytest.raises((TypeError, ValueError)):
            store.set("dev.example", "key", value)
        assert store.get("dev.example", "key") == "有效"


def test_sql_failure_rolls_back_and_next_write_can_succeed(tmp_path):
    with StorageService(tmp_path) as store:
        store.set("dev.example", "key", "有效")
        connection = sqlite3.connect(DataDirectories(tmp_path).structured_database())
        try:
            with connection:
                connection.execute(
                    "CREATE TRIGGER reject_update BEFORE UPDATE ON entries "
                    "BEGIN SELECT RAISE(ABORT, 'test failure'); END"
                )
            with pytest.raises(sqlite3.IntegrityError, match="test failure"):
                store.set("dev.example", "key", "无效")
            assert store.get("dev.example", "key") == "有效"
            with connection:
                connection.execute("DROP TRIGGER reject_update")
            store.set("dev.example", "key", "重试")
            assert store.get("dev.example", "key") == "重试"
        finally:
            connection.close()


def test_close_is_idempotent_and_releases_database(tmp_path):
    store = StorageService(tmp_path)
    store.set("dev.example", "key", 1)
    store.close()
    store.close()
    with pytest.raises(RuntimeError, match="已关闭"):
        store.get("dev.example", "key")
    with pytest.raises(RuntimeError, match="已关闭"):
        store.directory("dev.example")
    path = DataDirectories(tmp_path).structured_database()
    path.rename(tmp_path / "closed.sqlite3")


def test_owner_thread_is_required(tmp_path):
    with (
        StorageService(tmp_path) as store,
        ThreadPoolExecutor(max_workers=1) as pool,
        pytest.raises(RuntimeError, match="宿主线程"),
    ):
        pool.submit(store.get, "dev.example", "key").result()


def test_invalid_namespace_and_key_are_rejected(tmp_path):
    with StorageService(tmp_path) as store:
        with pytest.raises(ValueError, match="命名空间"):
            store.set("../outside", "key", 1)
        with pytest.raises(ValueError, match="非空字符串"):
            store.set("dev.example", "", 1)
        assert store.keys("dev.example") == ()


def test_unsupported_database_version_preserves_file_and_closes_connection(tmp_path):
    path = DataDirectories(tmp_path).structured_database()
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA user_version = 99")
    finally:
        connection.close()
    original = path.read_bytes()
    with pytest.raises(ValueError, match="版本"):
        StorageService(tmp_path)
    assert path.read_bytes() == original
    path.rename(tmp_path / "unsupported.sqlite3")
