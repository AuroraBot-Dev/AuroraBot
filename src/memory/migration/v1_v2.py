"""v1 → v2：durable facts 统一重作用域为 ``global``。

记忆契约演进后，长期事实跨会话共享（写入方只产生 ``scope="global"`` 的行）；
存量按会话隔离的事实必须重作用域，避免历史事实在查询中丢失。
逐行 ``INSERT OR IGNORE`` 保留最早来源行，随后删除残留会话行。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

_RESET_FACTS = (
    "INSERT OR IGNORE INTO durable_facts(scope, content, source_task_id, created_at) "
    "SELECT 'global', content, source_task_id, created_at FROM durable_facts WHERE scope != 'global'"
)
_DROP_SCOPED_FACTS = "DELETE FROM durable_facts WHERE scope != 'global'"


def migrate(connection: Any) -> None:
    connection.execute(text(_RESET_FACTS))
    connection.execute(text(_DROP_SCOPED_FACTS))
