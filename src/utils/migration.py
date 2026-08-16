"""版本化迁移框架：三个存储统一的初始化与迁移体系。

存储以「整数版本 + 逐版本迁移」演进：每个版本迁移是一个独立步骤
（如 ``engine/store/migration/v2_v3.py``），由 :func:`migrate_to` 从
当前版本按序执行到目标版本，并在每一步之后推进版本号。

版本号统一存于 ``schema_meta`` 表（缺失表 = v0 全新库），读写由
:func:`read_version` / :func:`write_version` 承担；engine、memory、ai 与
ops 存储的初始化都只调用 :func:`initialize_storage` 这一个入口。步骤执行
在调用方给出的事务上下文中进行。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import MetaData, text

type MigrationStep = Callable[[Any], None]
"""版本迁移步骤：``(connection) -> None``，把存储从版本 ``N`` 迁移到 ``N + 1``。"""


def read_version(connection: Any) -> int:
    """读取 schema_meta 版本号；无 schema_meta 表（全新库）视为 v0。"""
    has_meta = connection.execute(
        text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_meta'")
    ).scalar()
    if not has_meta:
        return 0
    version = connection.execute(text("SELECT version FROM schema_meta LIMIT 1")).scalar()
    return int(version) if version is not None else 0


def write_version(connection: Any, version: int) -> None:
    """覆写 schema_meta 版本号（单行表，先清后写）。"""
    connection.execute(text("DELETE FROM schema_meta"))
    connection.execute(text("INSERT INTO schema_meta(version) VALUES (:version)"), {"version": version})


def execute_script(connection: Any, script: str) -> None:
    """按 ``;`` 切分并逐条执行 DDL。

    SQLAlchemy 的 sqlite 驱动单次 ``execute`` 只允许一条语句，迁移脚本的
    多语句 DDL 需先切分。约定：步骤语句内容不含分号。
    """
    for statement in script.split(";"):
        if statement.strip():
            connection.execute(text(statement))


def initialize_storage(connection: Any, *, metadata: MetaData, steps: dict[int, MigrationStep], target: int) -> None:
    """统一初始化入口：v0 全新库建当前 Schema 并直达目标版本，旧库按版本序列迁移。

    全新库（无 ``schema_meta`` 表）由 ``metadata.create_all`` 建当前 Schema
    并直接写入目标版本（不重放历史步骤）；已有库经 :func:`migrate_to` 从
    当前版本逐级迁移，任一版本步骤失败时由调用方事务整体回滚。
    """
    current = read_version(connection)
    if current == 0:
        metadata.create_all(bind=connection, checkfirst=True)
        write_version(connection, target)
        current = target
    migrate_to(connection, current=current, target=target, steps=steps, set_version=write_version)


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
