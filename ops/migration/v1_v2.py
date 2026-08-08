"""面板存储 v1 → v2 迁移占位。

当前目标版本仍为 v1；当 Schema v2 确定后，在此实现
``migrate_v1_to_v2(connection)`` 并在 ``ops/migration/__init__.py``
的 ``STEPS`` 中注册、把 ``TARGET_VERSION`` 提升为 2。
"""

from __future__ import annotations
