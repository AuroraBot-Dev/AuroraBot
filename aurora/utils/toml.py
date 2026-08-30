"""读取 TOML 文件及常用强类型字段。"""

from __future__ import annotations

import math
import re
import tomllib
from collections.abc import Mapping
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from pathlib import Path

type TomlTable = Mapping[str, object]

_MAX_PORT = 65535
_WINDOWS_DRIVE_PREFIX_LENGTH = 3


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


def positive_number(table: TomlTable, key: str) -> float:
    value = table.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"配置字段 {key} 必须是有限正数")
    return float(value)


def optional_text(table: TomlTable, key: str) -> str | None:
    if key not in table:
        return None
    return text(table, key)


def raw_strings(table: TomlTable, key: str) -> tuple[str, ...]:
    value = table.get(key)
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"配置字段 {key} 必须是文本数组")
    return tuple(value)


def named_tables(document: TomlTable, key: str) -> Mapping[str, TomlTable]:
    values = table(document, key)
    result: dict[str, TomlTable] = {}
    for name, value in values.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(value, Mapping):
            raise ValueError(f"配置字段 {key} 必须只包含命名表")
        result[name.strip()] = cast("TomlTable", value)
    return result


def require_fields(document: TomlTable, allowed: frozenset[str], required: frozenset[str], label: str) -> None:
    names = set(document)
    unexpected = names - allowed
    missing = required - names
    if unexpected or missing:
        raise ValueError(f"{label} 字段不匹配：未知 {sorted(unexpected)}，缺少 {sorted(missing)}")


def require_exact_fields(document: TomlTable, expected: frozenset[str], label: str) -> None:
    names = set(document)
    if names != expected:
        raise ValueError(f"{label} 字段不匹配：未知 {sorted(names - expected)}，缺少 {sorted(expected - names)}")


def non_empty_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"配置字段 {field_name} 必须是非空文本")


def text_array(value: tuple[str, ...], field_name: str) -> None:
    if not isinstance(value, tuple) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"配置字段 {field_name} 必须是文本数组")


def check_positive_integer(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"配置字段 {field_name} 必须是正整数")


def check_positive_number(value: float, field_name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"配置字段 {field_name} 必须是有限正数")


def table_array(document: TomlTable, key: str) -> tuple[TomlTable, ...]:
    value = document.get(key)
    if not isinstance(value, tuple) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"配置字段 {key} 必须是表数组")
    return tuple(cast("TomlTable", item) for item in value)


def optional_table_array(document: TomlTable, key: str) -> tuple[TomlTable, ...]:
    value = document.get(key, ())
    if not isinstance(value, tuple) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"配置字段 {key} 必须是表数组")
    return tuple(cast("TomlTable", item) for item in value)


def optional_strings(table: TomlTable, key: str) -> tuple[str, ...]:
    if key not in table:
        return ()
    return strings(table, key)


def check_loopback_host(host: str, field_name: str) -> None:
    loopback_hosts = frozenset({"127.0.0.1", "::1", "localhost"})
    if host not in loopback_hosts:
        raise ValueError(f"配置字段 {field_name} 必须是 loopback 地址（127.0.0.1、::1 或 localhost）")


def check_port(port: int, field_name: str) -> None:
    check_positive_integer(port, field_name)
    if port > _MAX_PORT:
        raise ValueError(f"配置字段 {field_name} 必须在 1 到 {_MAX_PORT} 之间")


def check_unique_items(items: tuple[str, ...], field_name: str) -> None:
    if len(items) != len(set(items)):
        raise ValueError(f"配置字段 {field_name} 不得重复")


def check_http_origin(value: str, field_name: str) -> None:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"配置字段 {field_name} 必须是明确的 http(s) 来源")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise ValueError(f"配置字段 {field_name} 不得包含路径、查询或片段")
    if parts.username or parts.password:
        raise ValueError(f"配置字段 {field_name} 不得包含凭据")


def check_relative_directory(value: str, field_name: str) -> None:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    windows_absolute = (
        len(normalized) >= _WINDOWS_DRIVE_PREFIX_LENGTH and normalized[0].isalpha() and normalized[1:3] == ":/"
    )
    if not value.strip() or "\x00" in value or path.is_absolute() or windows_absolute or ".." in path.parts:
        raise ValueError(f"配置字段 {field_name} 必须是项目内相对目录")


def check_package_name(value: str, field_name: str) -> None:
    pattern = re.compile(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+")
    if pattern.fullmatch(value) is None:
        raise ValueError(f"配置字段 {field_name} 必须是小写点分包名")


def check_environment_name(value: str, field_name: str) -> None:
    pattern = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    if pattern.fullmatch(value) is None:
        raise ValueError(f"配置字段 {field_name} 必须是有效的环境变量名")


def non_empty_text_array(value: tuple[str, ...], field_name: str) -> None:
    if not value or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"配置字段 {field_name} 必须是非空文本数组")


def check_https_url(value: str, field_name: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(f"配置字段 {field_name} 必须是不含凭据或片段的 HTTPS URL")
