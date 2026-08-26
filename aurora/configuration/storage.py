"""注册 ``config/storage.toml``。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import load_toml, table, text

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class StorageConfig:
    data_root: str
    world: str
    ops: str


STORAGE_CONFIG = ConfigKey[StorageConfig]("storage")


def register(configs: ConfigCollector) -> None:
    configs.register(STORAGE_CONFIG, "config/storage.toml", _parse)


def _parse(path: Path) -> StorageConfig:
    storage = table(load_toml(path), "storage")
    return StorageConfig(
        _relative_directory(text(storage, "data_root"), "storage.data_root"),
        _relative_directory(text(storage, "world"), "storage.world"),
        _relative_directory(text(storage, "ops"), "storage.ops"),
    )


def _relative_directory(value: str, field: str) -> str:
    normalized = value.replace("\\", "/")
    drive_absolute = normalized[1:2] == ":" and normalized[:1].isalpha()
    if normalized.startswith("/") or drive_absolute:
        raise ValueError(f"{field} 必须是项目内相对目录")
    if any(part == ".." for part in normalized.split("/")):
        raise ValueError(f"{field} 必须是项目内相对目录")
    return normalized
