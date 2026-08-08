"""运行态存储 v7 → v8：mailbox 更名 messages 并精简队列列。

``mailbox`` 重建为 ``messages``：删除 ``available_at``/``lease_until``/
``attempts``（单进程独占，队列领取不再需要租约），索引更名为
``idx_messages_ready``/``idx_messages_agent``。
"""

from __future__ import annotations

from typing import Any

from src.utils.migration import execute_script

_SQL = """
DROP INDEX IF EXISTS idx_mailbox_ready;
DROP INDEX IF EXISTS idx_mailbox_agent;
ALTER TABLE mailbox RENAME TO mailbox_v7;
CREATE TABLE messages (
    message_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    target_agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    causation_id TEXT,
    correlation_id TEXT NOT NULL,
    priority INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
INSERT INTO messages (
    message_id, task_id, target_agent_id, type, payload_json, causation_id,
    correlation_id, priority, status, created_at, completed_at
)
SELECT message_id, task_id, target_agent_id, type, payload_json, causation_id,
    correlation_id, priority, status, created_at, completed_at
FROM mailbox_v7;
DROP TABLE mailbox_v7;
CREATE INDEX idx_messages_ready ON messages(status, priority DESC, created_at);
CREATE INDEX idx_messages_agent ON messages(target_agent_id, status, created_at);
"""


def migrate_v7_to_v8(connection: Any) -> None:
    """v7 → v8：mailbox 重建为精简列集的 messages。"""
    execute_script(connection, _SQL)
