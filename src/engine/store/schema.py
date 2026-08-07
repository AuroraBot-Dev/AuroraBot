"""SQLite DDL（Schema v9，RFC 0210）。

单一 SQLite 即运行态与归档；不迁移旧库（旧工作区拒绝启动）。
"""

from __future__ import annotations

from .status import ACT_ACTIVE

_SCHEMA_VERSION = 9

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    root_agent_id TEXT NOT NULL,
    root_message_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    root_summary TEXT NOT NULL,
    autonomous INTEGER NOT NULL CHECK (autonomous IN (0, 1)),
    status TEXT NOT NULL,
    model_calls INTEGER NOT NULL,
    tool_calls INTEGER NOT NULL,
    max_model_calls INTEGER NOT NULL,
    max_tool_calls INTEGER NOT NULL,
    max_duration_seconds REAL NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    termination_reason TEXT
);
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    parent_agent_id TEXT REFERENCES agents(agent_id),
    profile_id TEXT NOT NULL,
    depth INTEGER NOT NULL,
    assignment TEXT NOT NULL,
    status TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_summary TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_agents_task ON agents(task_id, status);
CREATE INDEX IF NOT EXISTS idx_agents_parent ON agents(parent_agent_id, status);
CREATE TABLE IF NOT EXISTS messages (
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
CREATE INDEX IF NOT EXISTS idx_messages_ready ON messages(status, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(target_agent_id, status, created_at);
CREATE TABLE IF NOT EXISTS activities (
    activity_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    kind TEXT NOT NULL CHECK (kind IN ('model', 'tool')),
    request_json TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_json TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_activities_ready ON activities(kind, status, priority DESC, created_at);
CREATE TABLE IF NOT EXISTS causal_events (
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
CREATE INDEX IF NOT EXISTS idx_causal_task ON causal_events(task_id, created_at);
CREATE TABLE IF NOT EXISTS inbox_events (
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
CREATE INDEX IF NOT EXISTS idx_inbox_due
ON inbox_events(status, available_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_inbox_session
ON inbox_events(session_id, status, created_at);
"""

_ACTIVE_ACTIVITY_INDEX = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS idx_activities_one_active_per_agent "
    f"ON activities(agent_id) WHERE status IN {ACT_ACTIVE}"
)
