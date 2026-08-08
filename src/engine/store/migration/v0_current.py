"""运行态存储 v0（全新库）→ 当前目标版本：直接建当前 Schema。

与其他存储不同，引擎运行态没有"初始版本"：全新库出生即当前目标版本
（RFC 0210，不重放历史版本）。v0 仅表示库中无 ``schema_meta`` 表，
本步骤不注册进 ``STEPS``（迁移框架按版本逐级推进，0 → 9 的整段跳跃
由 :meth:`src.engine.store.base.RuntimeStoreBase.initialize` 特判调用）。
"""

from __future__ import annotations

from typing import Any


def migrate_v0_to_current(connection: Any) -> None:
    """为全新库创建当前目标版本的全部表（ORM metadata 为唯一来源）。"""
    from src.engine.store.models import Base

    Base.metadata.create_all(bind=connection, checkfirst=True)
