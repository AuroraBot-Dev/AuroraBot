"""事务型 SQLite 仓库（Schema v10，SQLAlchemy ORM）—— Agent 运行时持久化的唯一入口。

由聚焦职责的 Mixin 组合而成，所有写操作均以单一 SQLAlchemy 事务边界为界。
"""

from __future__ import annotations

from .base import RuntimeStoreBase, utc_now
from .decisions import StoreDecisionsMixin
from .inbox import StoreInboxMixin
from .runtime import StoreRuntimeMixin


class SQLiteRuntimeStore(
    StoreDecisionsMixin,
    StoreInboxMixin,
    StoreRuntimeMixin,
    RuntimeStoreBase,
):
    """持久化 Task/Agent 工作流仓库：决策、Inbox 与状态查询三职责。"""


__all__ = ["SQLiteRuntimeStore", "utc_now"]
