"""运行态存储 v9 → v10：引入会话 generation、抢占和输出提交状态。"""

from __future__ import annotations

from typing import Any

from src.utils.migration import execute_script

_SQL = """
ALTER TABLE inbox_events ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE activities ADD COLUMN generation_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE activities ADD COLUMN publishable INTEGER NOT NULL DEFAULT 0;

CREATE TABLE session_lanes (
    session_id TEXT PRIMARY KEY,
    observed_revision INTEGER NOT NULL,
    generation_revision INTEGER NOT NULL,
    committed_revision INTEGER NOT NULL,
    generation_watermark INTEGER NOT NULL,
    active_task_id TEXT,
    interrupt_count INTEGER NOT NULL CHECK (interrupt_count >= 0),
    generation_started_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_session_lanes_active ON session_lanes(active_task_id);

CREATE TABLE output_publications (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    generation_revision INTEGER NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT OR IGNORE INTO session_lanes (
    session_id, observed_revision, generation_revision, committed_revision,
    generation_watermark, active_task_id, interrupt_count, generation_started_at, updated_at
)
SELECT session_id, 0, 0, 0, 0, NULL, 0, NULL, MAX(updated_at)
FROM tasks GROUP BY session_id;

INSERT OR IGNORE INTO session_lanes (
    session_id, observed_revision, generation_revision, committed_revision,
    generation_watermark, active_task_id, interrupt_count, generation_started_at, updated_at
)
SELECT session_id, 0, 0, 0, 0, NULL, 0, NULL, MAX(updated_at)
FROM inbox_events GROUP BY session_id;

UPDATE session_lanes
SET active_task_id = (
        SELECT task_id FROM tasks
        WHERE tasks.session_id = session_lanes.session_id
          AND tasks.status = 'ACTIVE' AND tasks.autonomous = 0
        ORDER BY tasks.started_at DESC, tasks.task_id DESC LIMIT 1
    ),
    generation_started_at = (
        SELECT started_at FROM tasks
        WHERE tasks.session_id = session_lanes.session_id
          AND tasks.status = 'ACTIVE' AND tasks.autonomous = 0
        ORDER BY tasks.started_at DESC, tasks.task_id DESC LIMIT 1
    );

UPDATE tasks
SET status = 'CANCELLED', termination_reason = 'superseded_by_v10_migration'
WHERE status = 'ACTIVE' AND autonomous = 0
  AND task_id NOT IN (SELECT active_task_id FROM session_lanes WHERE active_task_id IS NOT NULL);
UPDATE agents SET status = 'CANCELLED'
WHERE task_id IN (SELECT task_id FROM tasks WHERE termination_reason = 'superseded_by_v10_migration')
  AND status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED');
UPDATE messages SET status = 'ERROR'
WHERE task_id IN (SELECT task_id FROM tasks WHERE termination_reason = 'superseded_by_v10_migration')
  AND status IN ('PENDING', 'PROCESSING');
UPDATE activities SET status = 'CANCELLED'
WHERE task_id IN (SELECT task_id FROM tasks WHERE termination_reason = 'superseded_by_v10_migration')
  AND status IN ('PENDING', 'PROCESSING');
"""


def migrate_v9_to_v10(connection: Any) -> None:
    """v9 → v10：增加 session_lanes、revision、watermark 与提交标记。"""
    execute_script(connection, _SQL)
