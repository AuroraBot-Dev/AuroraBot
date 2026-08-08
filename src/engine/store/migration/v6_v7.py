"""运行态存储 v6 → v7：新增 inbox_events 持久化 Inbox。

建表与索引（``idx_inbox_due``/``idx_inbox_session``）逐一对齐 v7 档案，
RFC 0209 的防抖批次与 triage 输入自此持久化。
"""

from __future__ import annotations

from typing import Any

from src.utils.migration import execute_script

_SQL = """
CREATE TABLE inbox_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    type TEXT NOT NULL,
    summary TEXT NOT NULL,
    source_json TEXT NOT NULL,
    data_json TEXT NOT NULL,
    priority INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'TRIAGING', 'DEFERRED')),
    batch_id TEXT,
    available_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_inbox_due
    ON inbox_events(status, available_at, priority DESC, created_at);
CREATE INDEX idx_inbox_session
    ON inbox_events(session_id, status, created_at);
"""


def migrate_v6_to_v7(connection: Any) -> None:
    """v6 → v7：新建 inbox_events 表与索引。"""
    execute_script(connection, _SQL)
