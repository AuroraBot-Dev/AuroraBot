"""运行态存储 v8 → v9：删除冗余列（RFC 0210 精简）。

- ``activities.lease_until``：租约机制移除，直接 DROP COLUMN；
- ``agents.revision``：单进程无并发写，直接 DROP COLUMN；
- ``causal_events.external_message_id``：UNIQUE 列无法 DROP COLUMN，
  重建表删除（幂等由 correlation_id 承担）。
"""

from __future__ import annotations

from typing import Any

from ._execute import execute_script

_SQL = """
ALTER TABLE activities DROP COLUMN lease_until;
ALTER TABLE agents DROP COLUMN revision;
DROP INDEX IF EXISTS idx_causal_task;
ALTER TABLE causal_events RENAME TO causal_events_v8;
CREATE TABLE causal_events (
    event_id TEXT PRIMARY KEY,
    task_id TEXT,
    agent_id TEXT,
    type TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    causation_id TEXT,
    correlation_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
INSERT INTO causal_events (
    event_id, task_id, agent_id, type, summary, payload_json, causation_id,
    correlation_id, created_at
)
SELECT event_id, task_id, agent_id, type, summary, payload_json, causation_id,
    correlation_id, created_at
FROM causal_events_v8;
DROP TABLE causal_events_v8;
CREATE INDEX idx_causal_task ON causal_events(task_id, created_at);
"""


def migrate_v8_to_v9(connection: Any) -> None:
    """v8 → v9：删除 lease_until/revision/external_message_id 冗余列。"""
    execute_script(connection, _SQL)
