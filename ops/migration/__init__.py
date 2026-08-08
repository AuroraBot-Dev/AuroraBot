"""面板存储版本迁移序列（RFC 0217 §5）。

每个版本一个步骤文件（v0_v1.py、v1_v2.py…），在 ``STEPS`` 注册后由
:func:`src.utils.migration.migrate_to` 从当前版本按序执行到目标版本。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .v0_v1 import migrate_v0_to_v1

if TYPE_CHECKING:
    from src.utils.migration import MigrationStep

TARGET_VERSION = 1
STEPS: dict[int, "MigrationStep"] = {
    0: migrate_v0_to_v1,
}
