"""``aurorabot.world`` 的存储目录配置形状与解析。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from aurorabot.utils.validation import check_relative_directory

_VARIABLE = re.compile(r"%([A-Za-z0-9_]+)%")


@dataclass(frozen=True, slots=True)
class StorageEntry:
    """一个命名存储目录；path 可引用其他条目并递归展开。"""

    name: str
    path: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class StorageConfig:
    """``storage.toml`` 的全部存储目录。"""

    entries: tuple[StorageEntry, ...]


def resolve_storage_directory(entries: tuple[StorageEntry, ...], name: str) -> str:
    """按 name 查找目录并递归展开变量，返回规整后的项目相对路径。"""
    by_name = {entry.name: entry for entry in entries}
    if name not in by_name:
        raise ValueError(f"storage 目录尚未声明：{name}")
    resolved = _expand(by_name, name, set())
    check_relative_directory(resolved, f"storage.{name}")
    return _normalize(resolved)


def _expand(by_name: dict[str, StorageEntry], name: str, visiting: set[str]) -> str:
    if name in visiting:
        raise ValueError(f"storage 目录存在循环引用：{name}")
    entry = by_name[name]

    def replace(match: re.Match[str]) -> str:
        referenced = match.group(1)
        if referenced not in by_name:
            raise ValueError(f"storage 目录引用了未声明的变量：%{referenced}%")
        return _expand(by_name, referenced, visiting | {name})

    return _VARIABLE.sub(replace, entry.path)


def _normalize(path: str) -> str:
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    return "/".join(parts)
