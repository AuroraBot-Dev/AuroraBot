"""多语句 DDL 执行工具。

SQLAlchemy 的 sqlite 驱动单次 ``execute`` 只允许一条语句，迁移脚本的
DDL 按 ``;`` 切分后逐条执行。约定：迁移步骤中的语句内容不含分号。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text


def execute_script(connection: Any, script: str) -> None:
    """按 ``;`` 切分并逐条执行 DDL，跳过空语句。"""
    for statement in script.split(";"):
        if statement.strip():
            connection.execute(text(statement))
