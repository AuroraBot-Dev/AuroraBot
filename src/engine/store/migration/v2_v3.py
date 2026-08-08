"""运行态存储 v2 → v3：重建 activities，kind 增加 'publication'。

重建表以便放宽 ``kind`` CHECK（'model'/'effect' → 'model'/'effect'/
'publication'）；旧数据原样搬入。步骤语义重建自演化档案
``_ACTIVITIES_V3``，并补回被旧脚本丢弃的部分唯一索引。
"""

from __future__ import annotations

from typing import Any

from ._execute import execute_script

_SQL = """
DROP INDEX IF EXISTS idx_activities_one_active_per_agent;
DROP INDEX IF EXISTS idx_activities_ready;
ALTER TABLE activities RENAME TO activities_v2;
CREATE TABLE activities (
    activity_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    kind TEXT NOT NULL CHECK (kind IN ('model', 'effect', 'publication')),
    request_json TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    lease_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_json TEXT,
    error TEXT
);
INSERT INTO activities SELECT * FROM activities_v2;
DROP TABLE activities_v2;
CREATE INDEX idx_activities_ready ON activities(kind, status, priority DESC, created_at);
CREATE UNIQUE INDEX idx_activities_one_active_per_agent
    ON activities(agent_id) WHERE status IN ('PENDING', 'PROCESSING');
"""


def migrate_v2_to_v3(connection: Any) -> None:
    """v2 → v3：重建 activities 表（kind 增加 'publication'）。"""
    execute_script(connection, _SQL)
