"""注册 ``config/storage.toml``。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import check_relative_directory, load_toml, table, text

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class StorageConfig:
    data_root: str
    world: str
    ops: str

    def __post_init__(self) -> None:
        check_relative_directory(self.data_root, "storage.data_root")
        check_relative_directory(self.world, "storage.world")
        check_relative_directory(self.ops, "storage.ops")


STORAGE_CONFIG = ConfigKey[StorageConfig]("storage")


def register(configs: ConfigCollector) -> None:
    configs.register(STORAGE_CONFIG, "config/storage.toml", _parse)


def _parse(path: Path) -> StorageConfig:
    storage = table(load_toml(path), "storage")
    return StorageConfig(
        text(storage, "data_root"),
        text(storage, "world"),
        text(storage, "ops"),
    )
