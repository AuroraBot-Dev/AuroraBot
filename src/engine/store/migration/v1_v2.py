"""运行态存储 v1 → v2：版本推进占位。

v1 结构未留存档案（演化档案自 v2 起），本步仅推进版本号；若旧库缺失
``schema_meta`` 表，启动时按全新库处理。
"""

from __future__ import annotations

from typing import Any


def migrate_v1_to_v2(connection: Any) -> None:
    """v1 → v2：无结构变更，仅推进版本号。"""
