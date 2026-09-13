"""解析并注册 ``config/storage.toml`` 的存储路径目录。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.contracts.config import ConfigSpec
from aurora.utils.toml import load_toml, optional_text, table_array, text
from src.world.config import StorageConfig, StorageEntry, resolve_storage_directory

if TYPE_CHECKING:
    from pathlib import Path


def _parse(path: Path) -> StorageConfig:
    raw_entries = table_array(load_toml(path), "storage")
    entries = tuple(
        StorageEntry(
            text(item, "name"),
            text(item, "path"),
            optional_text(item, "description") or "",
        )
        for item in raw_entries
    )
    names = [entry.name for entry in entries]
    if not names:
        raise ValueError("storage.toml 至少需要声明一个目录")
    if len(names) != len(set(names)):
        raise ValueError("storage 目录名不能重复")
    return StorageConfig(entries)


def resolve_directory(entries: tuple[StorageEntry, ...], name: str) -> str:
    """按 name 查找目录并递归展开变量，返回规整后的项目相对路径。"""
    return resolve_storage_directory(entries, name)


STORAGE_CONFIG = ConfigSpec[StorageConfig](
    name="storage",
    path="config/storage.toml",
    parse=_parse,
)

CONFIG_SPEC = STORAGE_CONFIG
