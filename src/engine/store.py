"""事务型 SQLite 仓库，由聚焦职责的 Mixin 组合而成。"""

from src.engine.store_activities import StoreActivitiesMixin
from src.engine.store_base import RuntimeStoreBase, utc_now
from src.engine.store_decisions import StoreDecisionsMixin
from src.engine.store_ingress import StoreIngressMixin
from src.engine.store_queries import StoreQueriesMixin


class SQLiteRuntimeStore(
    StoreDecisionsMixin,
    StoreActivitiesMixin,
    StoreQueriesMixin,
    StoreIngressMixin,
    RuntimeStoreBase,
):
    """持久化 Task/Agent 工作流仓库，以单一 SQLite 事务边界为界。

    通过多重继承组合以下 Mixin：
    - StoreDecisionsMixin：原子决策提交、监督更新与 Task 终止
    - StoreActivitiesMixin：模型与工具 Activity 出站操作
    - StoreQueriesMixin：只读查询与情境管理
    - StoreIngressMixin：Task 入口、工具回执与邮箱租赁
    """


__all__ = ["SQLiteRuntimeStore", "utc_now"]
