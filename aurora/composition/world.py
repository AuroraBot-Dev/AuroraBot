"""构造并导出 ``src.world`` 的项目实例。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from aurora.composer import InstanceKey
from aurora.configuration.storage import STORAGE_CONFIG
from src.contracts import WorldJournal
from src.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from aurora.composer import CompositionContext


WORLD_JOURNAL = InstanceKey[WorldJournal]("world.journal")


def register(context: CompositionContext) -> None:
    values = context.config.get(STORAGE_CONFIG).values
    storage = values.get("storage")
    if not isinstance(storage, Mapping):
        raise ValueError("storage.toml 缺少 [storage]")
    data_root = _relative_directory(storage.get("data_root"), "storage.data_root")
    world_root = _relative_directory(storage.get("world", "world"), "storage.world")
    database_path = context.config.project_root / data_root / world_root / "world.sqlite3"
    context.provide(WORLD_JOURNAL, SqlAlchemyWorldJournal(database_path))


def _relative_directory(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空相对目录")
    if value.startswith("/") or ".." in value.split("/"):
        raise ValueError(f"{field} 必须是项目内相对目录")
    return value
