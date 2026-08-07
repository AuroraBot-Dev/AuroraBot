"""TOML 配置解析校验工具。

供 ``src.config`` 各解析器共享；只做结构校验，不接触文件 I/O。
"""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from typing import Any

from src.contracts.configuration import ConfigurationError


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    UNEXPECTED_OR_MISSING_KEYS = "{label} has unexpected {unexpected} or missing {missing} keys"
    MUST_BE_TABLE = "{label} must be a table"
    MUST_BE_NON_EMPTY_STRING = "{label} must be a non-empty string"
    MUST_BE_POSITIVE = "{label} must be positive"


def _require_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    """检查字典键恰好为指定集合，不允许多余或缺失。"""
    unexpected = set(value) - keys
    missing = keys - set(value)
    if unexpected or missing:
        raise ConfigurationError(
            _Msg.UNEXPECTED_OR_MISSING_KEYS.format(label=label, unexpected=sorted(unexpected), missing=sorted(missing))
        )


def _table(value: object, label: str) -> dict[str, Any]:
    """校验值为 TOML 表（dict）类型。"""
    if not isinstance(value, dict):
        raise ConfigurationError(_Msg.MUST_BE_TABLE.format(label=label))
    return value


def _string(value: object, label: str) -> str:
    """校验值为非空字符串。"""
    if not isinstance(value, str) or not value:
        raise ConfigurationError(_Msg.MUST_BE_NON_EMPTY_STRING.format(label=label))
    return value


def _positive_number(value: object, label: str) -> float:
    """校验值为正数（int 或 float），返回 float。"""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0 or not isfinite(value):
        raise ConfigurationError(_Msg.MUST_BE_POSITIVE.format(label=label))
    return float(value)
