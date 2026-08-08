"""记忆存储 v0 → v1：创建 memory.sqlite3 全部表（RFC 0216/0217）。

v0 表示全新（或尚未版本化）的库；本步骤与 ORM metadata 保持同一
来源，后续版本迁移沿用此模式。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text


def migrate_v0_to_v1(connection: Any) -> None:
    """创建记忆 Schema v1 的全部表并清理历史遗留表。"""
    from src.memory.service import _Base

    connection.execute(text("DROP TABLE IF EXISTS completed_tasks"))
    _Base.metadata.create_all(bind=connection, checkfirst=True)
