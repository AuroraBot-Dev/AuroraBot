"""Transactional SQLite store composed from focused workflow repositories."""

from src.kernel.store_activities import StoreActivitiesMixin
from src.kernel.store_base import RuntimeStoreBase, utc_now
from src.kernel.store_decisions import StoreDecisionsMixin
from src.kernel.store_ingress import StoreIngressMixin
from src.kernel.store_queries import StoreQueriesMixin


class SQLiteRuntimeStore(
    StoreDecisionsMixin,
    StoreActivitiesMixin,
    StoreQueriesMixin,
    StoreIngressMixin,
    RuntimeStoreBase,
):
    """Durable Task/Agent workflow store with one SQLite transaction boundary."""


__all__ = ["SQLiteRuntimeStore", "utc_now"]
