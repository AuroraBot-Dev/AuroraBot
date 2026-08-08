"""面板存储 v0 → v1：创建 sessions 与 attachments 表（RFC 0218 §6）。

v0 表示全新（或尚未版本化）的库；本步骤与 ORM metadata 保持同一
来源，后续版本迁移沿用此模式。
"""

from __future__ import annotations

from typing import Any


def migrate_v0_to_v1(connection: Any) -> None:
    """创建面板 Schema v1 的全部表（sessions 与 attachments）。"""
    from ops.store import _Base

    _Base.metadata.create_all(bind=connection, checkfirst=True)
