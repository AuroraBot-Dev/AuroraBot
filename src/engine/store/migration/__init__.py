"""engine 运行态存储版本迁移序列（RFC 0217 §5）。

版本号存于 ``schema_meta`` 表（RFC 0210 契约）。当前目标版本为 9；
v1-v8 迁移步骤按历史演化档案重建（RFC 0210 §3：自即日起数据库必须
考虑迁移，旧库启动时按序升级到 v9；代码路径只访问 v9 形状）。
未来 Schema 演进时在此新增步骤文件（如 ``v9_v10.py``）并在 ``STEPS``
注册、提升 ``TARGET_VERSION``。
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

if TYPE_CHECKING:
    from src.utils.migration import MigrationStep

TARGET_VERSION = 9
STEPS: dict[int, "MigrationStep"] = {
    1: migrate_v1_to_v2,
    2: migrate_v2_to_v3,
    3: migrate_v3_to_v4,
    4: migrate_v4_to_v5,
    5: migrate_v5_to_v6,
    6: migrate_v6_to_v7,
    7: migrate_v7_to_v8,
    8: migrate_v8_to_v9,
}
