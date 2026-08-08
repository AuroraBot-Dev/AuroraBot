"""版本化迁移框架（RFC 0217 §5）。

存储以「整数版本 + 逐版本迁移」演进：每个版本迁移是一个独立步骤
（如 ``ops/migration/v0_v1.py``），由 :func:`migrate_to` 从当前版本
按序执行到目标版本，并在每一步之后推进版本号。版本号读写由调用方
提供（``PRAGMA user_version`` / ``schema_meta`` 等），框架不绑定
具体存储或驱动；步骤执行在调用方给出的事务上下文中进行。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

type MigrationStep = Callable[[Any], None]
"""版本迁移步骤：``(connection) -> None``，把存储从版本 ``N`` 迁移到 ``N + 1``。"""


def migrate_to(
    connection: Any,
    *,
    current: int,
    target: int,
    steps: dict[int, MigrationStep],
    set_version: Callable[[Any, int], None],
) -> None:
    """把存储从 ``current`` 逐版本迁移到 ``target``。

    - ``current > target``：数据库版本比代码支持的更新，拒绝启动；
    - 缺失步骤：任何版本间隔都必须有显式步骤（纯版本号推进也需提供
      no-op 步骤），防止静默漏迁移；
    - 每步执行成功后立即推进版本号（``set_version(connection, N + 1)``）。
    """
    if current > target:
        raise RuntimeError(f"storage schema version {current} is newer than supported {target}")
    for version in range(current, target):
        step = steps.get(version)
        if step is None:
            raise RuntimeError(f"missing migration step for schema version {version} -> {version + 1}")
        step(connection)
        set_version(connection, version + 1)
