"""解析并注册 ``config/storage.toml`` 的存储路径目录。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora.config import ConfigSpec
from aurora.utils.toml import (
    check_relative_directory,
    load_toml,
    optional_text,
    table_array,
    text,
)

if TYPE_CHECKING:
    from pathlib import Path

_VARIABLE = re.compile(r"%([A-Za-z0-9_]+)%")


@dataclass(frozen=True, slots=True)
class StorageEntry:
    """一个命名存储目录；path 可引用其他条目并递归展开。"""

    name: str
    path: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class StorageConfig:
    """命名存储目录集合；resolve() 展开 ``%VAR%`` 引用并规整路径。"""

    entries: tuple[StorageEntry, ...]

    def resolve(self, name: str) -> str:
        """按 name 查找目录并递归展开变量，返回规整后的项目相对路径。"""
        by_name = {entry.name: entry for entry in self.entries}
        if name not in by_name:
            raise ValueError(f"storage 目录尚未声明：{name}")
        resolved = _expand(by_name, name, set())
        check_relative_directory(resolved, f"storage.{name}")
        return _normalize(resolved)


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


def _expand(
    by_name: dict[str, StorageEntry],
    name: str,
    visiting: set[str],
) -> str:
    """递归展开一个条目的 path；visiting 检测循环引用。"""
    if name in visiting:
        raise ValueError(f"storage 目录存在循环引用：{name}")
    entry = by_name[name]
    raw = entry.path

    def replace(match: re.Match[str]) -> str:
        referenced = match.group(1)
        if referenced not in by_name:
            raise ValueError(f"storage 目录引用了未声明的变量：%{referenced}%")
        return _expand(by_name, referenced, visiting | {name})

    return _VARIABLE.sub(replace, raw)


def _normalize(path: str) -> str:
    """规整相对路径：合并重复斜杠、移除尾斜杠。"""
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    return "/".join(parts)


STORAGE_CONFIG = ConfigSpec[StorageConfig](
    name="storage",
    path="config/storage.toml",
    parse=_parse,
)
