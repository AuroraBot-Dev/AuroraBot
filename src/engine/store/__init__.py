"""事务型 SQLite 仓库 —— Agent 运行时持久化的唯一入口。

由聚焦职责的 Mixin 组合而成，所有写操作均以单一 SQLite 事务边界为界。
"""

from __future__ import annotations

from .activities import StoreActivitiesMixin
from .base import RuntimeStoreBase, utc_now
from .decisions import StoreDecisionsMixin
from .ingress import StoreIngressMixin
from .queries import StoreQueriesMixin


class SQLiteRuntimeStore(
    StoreDecisionsMixin,
    StoreActivitiesMixin,
    StoreQueriesMixin,
    StoreIngressMixin,
    RuntimeStoreBase,
):
    """持久化 Task/Agent 工作流仓库，以单一 SQLite 事务边界为界。"""


__all__ = ["SQLiteRuntimeStore", "utc_now"]
