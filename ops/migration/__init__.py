"""面板存储版本迁移序列。

版本号统一存于 ``schema_meta`` 表（utils.migration 读写）；当前目标
版本为 1，初始 schema 即 v1，无历史迁移步骤（``STEPS`` 为空）。
未来 Schema 演进时新增步骤文件（如 ``v1_v2.py``）并在 ``STEPS``
注册、提升 ``TARGET_VERSION``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.utils.migration import MigrationStep

TARGET_VERSION = 1
STEPS: dict[int, "MigrationStep"] = {}
