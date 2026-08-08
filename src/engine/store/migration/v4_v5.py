"""运行态存储 v4 → v5：重建 activities，kind 归一为 'model'/'tool'。

'effect'/'publication' 活动归入 'tool'，并在 ``request_json`` 中写入
``legacy_kind`` 保留原种类。步骤语义重建自演化档案 ``_ACTIVITIES_V5``，
并补回被旧脚本丢弃的部分唯一索引。
"""

from __future__ import annotations

from typing import Any

from src.utils.migration import execute_script

_SQL = """
DROP INDEX IF EXISTS idx_activities_one_active_per_agent;
DROP INDEX IF EXISTS idx_activities_ready;
ALTER TABLE activities RENAME TO activities_v4;
CREATE TABLE activities (
    activity_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    kind TEXT NOT NULL CHECK (kind IN ('model', 'tool')),
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
INSERT INTO activities (
    activity_id, task_id, agent_id, kind, request_json, status, priority,
    idempotency_key, lease_until, created_at, updated_at, result_json, error
)
SELECT activity_id, task_id, agent_id,
    CASE WHEN kind = 'model' THEN 'model' ELSE 'tool' END,
    CASE WHEN kind = 'model' THEN request_json
         ELSE json_set(request_json, '$.legacy_kind', kind) END,
    status, priority, idempotency_key, lease_until, created_at, updated_at,
    result_json, error
FROM activities_v4;
DROP TABLE activities_v4;
CREATE INDEX idx_activities_ready ON activities(kind, status, priority DESC, created_at);
CREATE UNIQUE INDEX idx_activities_one_active_per_agent
    ON activities(agent_id) WHERE status IN ('PENDING', 'PROCESSING');
"""


def migrate_v4_to_v5(connection: Any) -> None:
    """v4 → v5：重建 activities，kind 归一为 'model'/'tool'。"""
    execute_script(connection, _SQL)
