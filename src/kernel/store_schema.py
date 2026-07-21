"""SQLite Agent runtime schema and migration constants."""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    root_agent_id TEXT NOT NULL,
    root_message_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    audience_ref TEXT NOT NULL,
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
    revision INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_summary TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_agents_task ON agents(task_id, status);
CREATE INDEX IF NOT EXISTS idx_agents_parent ON agents(parent_agent_id, status);
CREATE TABLE IF NOT EXISTS mailbox (
    message_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    target_agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    causation_id TEXT,
    correlation_id TEXT NOT NULL,
    priority INTEGER NOT NULL,
    status TEXT NOT NULL,
    available_at TEXT NOT NULL,
    lease_until TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_mailbox_ready ON mailbox(status, priority DESC, available_at, created_at);
CREATE INDEX IF NOT EXISTS idx_mailbox_agent ON mailbox(target_agent_id, status, created_at);
CREATE TABLE IF NOT EXISTS activities (
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
    external_message_id TEXT UNIQUE,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_causal_task ON causal_events(task_id, created_at);
CREATE TABLE IF NOT EXISTS situations (
    situation_id TEXT PRIMARY KEY,
    audience_ref TEXT NOT NULL,
    source TEXT NOT NULL,
    type TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    priority INTEGER NOT NULL,
    status TEXT NOT NULL,
    claimed_by_agent_id TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_situations_open ON situations(status, expires_at, priority DESC);
"""

_SCHEMA_VERSION = 5
_ACTIVE_ACTIVITY_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_activities_one_active_per_agent "
    "ON activities(agent_id) WHERE status IN ('PENDING', 'PROCESSING')"
)
_ACTIVITIES_V5 = """
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
INSERT INTO activities
SELECT activity_id, task_id, agent_id,
       CASE WHEN kind = 'model' THEN 'model' ELSE 'tool' END,
       CASE WHEN kind = 'model' THEN request_json
            ELSE json_set(request_json, '$.legacy_kind', kind) END,
       status, priority, idempotency_key, lease_until, created_at, updated_at, result_json, error
FROM activities_v4;
DROP TABLE activities_v4;
CREATE INDEX idx_activities_ready ON activities(kind, status, priority DESC, created_at);
"""
