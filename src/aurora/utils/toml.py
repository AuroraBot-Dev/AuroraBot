"""读取 TOML 文件及常用强类型字段。"""

from __future__ import annotations

import math
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


def boolean(table: TomlTable, key: str) -> bool:
    value = table.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"配置字段 {key} 必须是布尔值")
    return value


def positive_number(table: TomlTable, key: str) -> float:
    value = table.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"配置字段 {key} 必须是有限正数")
    return float(value)


def optional_text(table: TomlTable, key: str) -> str | None:
    if key not in table:
        return None
    return text(table, key)


def require_fields(document: TomlTable, allowed: frozenset[str], required: frozenset[str], label: str) -> None:
    names = set(document)
    unexpected = names - allowed
    missing = required - names
    if unexpected or missing:
        raise ValueError(f"{label} 字段不匹配：未知 {sorted(unexpected)}，缺少 {sorted(missing)}")


def table_array(document: TomlTable, key: str) -> tuple[TomlTable, ...]:
    value = document.get(key)
    if not isinstance(value, tuple) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"配置字段 {key} 必须是表数组")
    return tuple(cast("TomlTable", item) for item in value)
