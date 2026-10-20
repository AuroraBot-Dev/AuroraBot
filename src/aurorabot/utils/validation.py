"""无项目语义的通用配置值校验。"""

from __future__ import annotations

import math
import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit

_WINDOWS_DRIVE_PREFIX_LENGTH = 3


def check_positive_number(value: float, field_name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"配置字段 {field_name} 必须是有限正数")


def check_unique_items(items: tuple[str, ...], field_name: str) -> None:
    if len(items) != len(set(items)):
        raise ValueError(f"配置字段 {field_name} 不得重复")


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


def check_non_empty_text_array(value: tuple[str, ...], field_name: str) -> None:
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
