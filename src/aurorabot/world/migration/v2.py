"""为已存在的世界事实补充可确认的获知时间下界。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection


def apply(connection: Connection) -> None:
    """已有事实无法推断原始获知时间，以本次确认时间作为保守边界。"""
    connection.execute(
        text("ALTER TABLE world_commits ADD COLUMN recorded_at DATETIME NOT NULL DEFAULT '1970-01-01 00:00:00.000000'")
    )
    connection.execute(
        text("UPDATE world_commits SET recorded_at = :recorded_at"),
        {"recorded_at": datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")},
    )
    connection.execute(text("CREATE INDEX world_commit_recorded_at ON world_commits (recorded_at)"))
