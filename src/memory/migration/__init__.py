"""记忆存储版本迁移序列。

版本号统一存于 ``schema_meta`` 表（utils.migration 读写）。Schema 演进
时新增步骤文件（如 ``v1_v2.py``）并在 ``STEPS`` 注册、提升 ``TARGET_VERSION``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.memory.migration.v1_v2 import migrate as v1_v2

if TYPE_CHECKING:
    from src.utils.migration import MigrationStep

TARGET_VERSION = 2
STEPS: dict[int, "MigrationStep"] = {1: v1_v2}
