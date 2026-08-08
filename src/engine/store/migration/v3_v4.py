"""运行态存储 v3 → v4：引入 audience 阶段。

- ``tasks``/``situations`` 增加 ``audience_ref``（SQLite 加列须带 DEFAULT，
  旧行以空串填充，语义为"无 audience"）；
- 新增 ``reply_grants`` 表及其索引（演化档案 ``_REPLY_ROUTE_INDEX``）。
"""

from __future__ import annotations

from typing import Any

from src.utils.migration import execute_script

_SQL = """
ALTER TABLE tasks ADD COLUMN audience_ref TEXT NOT NULL DEFAULT '';
ALTER TABLE situations ADD COLUMN audience_ref TEXT NOT NULL DEFAULT '';
CREATE TABLE reply_grants (
    endpoint_id TEXT NOT NULL,
    route_ref TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    capability_id TEXT NOT NULL,
    audience_ref TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation = 'reply'),
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'REVOKED')),
    PRIMARY KEY (task_id, endpoint_id, route_ref),
    UNIQUE (endpoint_id, route_ref)
);
CREATE INDEX idx_reply_grants_task ON reply_grants(task_id, status, expires_at);
CREATE UNIQUE INDEX idx_reply_grants_endpoint_route ON reply_grants(endpoint_id, route_ref);
"""


def migrate_v3_to_v4(connection: Any) -> None:
    """v3 → v4：audience_ref 加列 + 新建 reply_grants。"""
    execute_script(connection, _SQL)
