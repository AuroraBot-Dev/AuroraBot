"""1 → 2：把域补齐为可独立扫描的分区索引。

`delta()` 只按 `(scope, sequence)` 判断提交是否越过观察前沿，提交正文在其之后才载入；
分区索引让这段判断成为一次覆盖索引的范围查找，不再回落到 `world_commits` 全表扫描。
只增加索引，不改动任何提交数据。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS world_commit_scope_partition ON world_commit_scopes (scope, sequence, commit_id)",
)


def apply(connection: Connection) -> None:
    for statement in _STATEMENTS:
        connection.execute(text(statement))
