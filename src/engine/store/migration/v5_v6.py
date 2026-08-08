"""运行态存储 v5 → v6：撤回 audience 机制。

audience 阶段（v4 引入）被整体移除：``reply_grants``/``situations`` 表
删除，``tasks.audience_ref`` 列删除。v7 档案中已无 audience 痕迹，
本步为其过渡版本。
"""

from __future__ import annotations

from typing import Any

from ._execute import execute_script

_SQL = """
DROP TABLE IF EXISTS reply_grants;
DROP TABLE IF EXISTS situations;
ALTER TABLE tasks DROP COLUMN audience_ref;
"""


def migrate_v5_to_v6(connection: Any) -> None:
    """v5 → v6：删除 reply_grants、situations 与 tasks.audience_ref。"""
    execute_script(connection, _SQL)
