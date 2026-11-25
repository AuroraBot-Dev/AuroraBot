"""按命名空间组织的同步结构化存储服务。"""

import sqlite3
from pathlib import Path
from threading import get_ident
from types import TracebackType
from typing import Self

from .directories import DataDirectories
from .ids import validate_namespace
from .json_data import decode_json, encode_json
from .snapshots import JsonSnapshotStore


class StorageService:
    """管理宿主目录、ctx 快照入口及 SQLite JSON 键值存储。

    单次 set/delete 以事务提交；get 缺失抛出 KeyError，keys 按键排序。
    接口限创建线程同步调用。命名空间表达归属，不限制内部跨命名空间访问。
    服务实例由宿主持有，不进入 ctx；插件自行创建的数据库连接由插件释放。
    """

    def __init__(self, root: Path) -> None:
        self._directories = DataDirectories(root)
        self._owner = get_ident()
        self._closed = False
        connection = sqlite3.connect(self._directories.structured_database())
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError(f"不支持的结构化存储版本：{version}")
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS entries ("
                    "namespace TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
                    "PRIMARY KEY (namespace, key))"
                )
                connection.execute("PRAGMA user_version = 1")
        except BaseException:
            connection.close()
            raise
        self._connection = connection

    def _check_owner(self) -> None:
        if get_ident() != self._owner:
            raise RuntimeError("存储接口必须在创建它的宿主线程调用")

    def _check_open(self) -> None:
        self._check_owner()
        if self._closed:
            raise RuntimeError("存储服务已关闭")

    def _check_key(self, namespace: str, key: str) -> None:
        self._check_open()
        validate_namespace(namespace)
        if not isinstance(key, str) or not key:
            raise ValueError("存储键必须为非空字符串")

    def directory(self, namespace: str) -> Path:
        """返回插件自行维护文件、数据库及迁移的目录。"""
        self._check_open()
        return self._directories.namespace(namespace)

    def snapshot_store(self) -> JsonSnapshotStore:
        """提供完整 ctx JSON 快照的统一路径；由 ContextPersistence 调度 I/O。"""
        self._check_open()
        return JsonSnapshotStore(self._directories.context_snapshot())

    def configuration_directory(self) -> Path:
        """返回宿主统一配置目录。"""
        self._check_open()
        return self._directories.configuration()

    def get(self, namespace: str, key: str) -> object:
        self._check_key(namespace, key)
        row = self._connection.execute(
            "SELECT value FROM entries WHERE namespace = ? AND key = ?", (namespace, key)
        ).fetchone()
        if row is None:
            raise KeyError((namespace, key))
        return decode_json(row[0])

    def set(self, namespace: str, key: str, value: object) -> None:
        """整项替换并立即提交；编码或 SQL 失败时保留已提交内容。"""
        self._check_key(namespace, key)
        encoded = encode_json(value)
        with self._connection:
            self._connection.execute(
                "INSERT INTO entries(namespace, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(namespace, key) DO UPDATE SET value = excluded.value",
                (namespace, key, encoded),
            )

    def delete(self, namespace: str, key: str) -> bool:
        self._check_key(namespace, key)
        with self._connection:
            cursor = self._connection.execute("DELETE FROM entries WHERE namespace = ? AND key = ?", (namespace, key))
        return cursor.rowcount > 0

    def keys(self, namespace: str) -> tuple[str, ...]:
        self._check_open()
        validate_namespace(namespace)
        rows = self._connection.execute("SELECT key FROM entries WHERE namespace = ? ORDER BY key", (namespace,))
        return tuple(row[0] for row in rows)

    def close(self) -> None:
        """幂等关闭框架连接；宿主须先结束工作组件并完成 ctx 最后落盘。"""
        self._check_owner()
        if not self._closed:
            self._connection.close()
            self._closed = True

    def __enter__(self) -> Self:
        self._check_open()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None
    ) -> None:
        self.close()
