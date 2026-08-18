"""读取 TOML 文件及常用强类型字段。"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path

type TomlTable = Mapping[str, object]


def load_toml(path: Path) -> TomlTable:
    with path.open("rb") as stream:
        return cast("TomlTable", _freeze(tomllib.load(stream)))


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def table(document: TomlTable, key: str) -> TomlTable:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"配置字段 {key} 必须是表")
    return cast("TomlTable", value)


def text(table: TomlTable, key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"配置字段 {key} 必须是非空文本")
    return value.strip()


def strings(table: TomlTable, key: str) -> tuple[str, ...]:
    value = table.get(key)
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"配置字段 {key} 必须是文本数组")
    return tuple(item.strip() for item in value)


def positive_integer(table: TomlTable, key: str) -> int:
    value = table.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"配置字段 {key} 必须是正整数")
    return value


def string_mapping(table: TomlTable, key: str) -> Mapping[str, str]:
    value = table.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"配置字段 {key} 必须是表")
    result: dict[str, str] = {}
    for item_key, item_value in value.items():
        valid_key = isinstance(item_key, str) and bool(item_key.strip())
        valid_value = isinstance(item_value, str) and bool(item_value.strip())
        if not valid_key or not valid_value:
            raise ValueError(f"配置字段 {key} 必须只包含非空文本键值")
        assert isinstance(item_key, str)
        assert isinstance(item_value, str)
        result[item_key.strip()] = item_value.strip()
    return result
