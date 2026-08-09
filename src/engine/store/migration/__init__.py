"""engine 运行态存储版本迁移序列。

版本号统一存于 ``schema_meta`` 表，由 utils.migration 读写。
当前目标版本为 10；v1-v9 迁移步骤按历史演化档案重建。数据库演进必须提供迁移，旧库启动时按序升级到 v10，代码路径只
访问 v10 形状。全新库（无 ``schema_meta``，v0）不注册步骤，由
initialize_storage 直接建当前 Schema（全新库出生即目标版本，
不重放历史）。未来 Schema 演进时在此新增步骤文件（如 ``v9_v10.py``）
并在 ``STEPS`` 注册、提升 ``TARGET_VERSION``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .v1_v2 import migrate_v1_to_v2
from .v2_v3 import migrate_v2_to_v3
from .v3_v4 import migrate_v3_to_v4
from .v4_v5 import migrate_v4_to_v5
from .v5_v6 import migrate_v5_to_v6
from .v6_v7 import migrate_v6_to_v7
from .v7_v8 import migrate_v7_to_v8
from .v8_v9 import migrate_v8_to_v9
from .v9_v10 import migrate_v9_to_v10

if TYPE_CHECKING:
    from src.utils.migration import MigrationStep

TARGET_VERSION = 10
STEPS: dict[int, "MigrationStep"] = {
    1: migrate_v1_to_v2,
    2: migrate_v2_to_v3,
    3: migrate_v3_to_v4,
    4: migrate_v4_to_v5,
    5: migrate_v5_to_v6,
    6: migrate_v6_to_v7,
    7: migrate_v7_to_v8,
    8: migrate_v8_to_v9,
    9: migrate_v9_to_v10,
}
