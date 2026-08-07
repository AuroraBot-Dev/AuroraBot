"""配置文件读取与可审计来源快照。"""

from __future__ import annotations

import hashlib
import tomllib
from typing import TYPE_CHECKING, Any

from src.contracts import (
    ConfigurationError,
    ConfigurationSource,
)

if TYPE_CHECKING:
    from pathlib import Path


def read_source(path: Path) -> tuple[bytes, ConfigurationSource]:
    """读取文件并返回原始内容及 SHA-256 来源快照。"""
    path = path.resolve()
    try:
        content = path.read_bytes()
    except OSError as error:
        raise ConfigurationError(f"configuration file cannot be read: {path}") from error
    return content, ConfigurationSource(path, hashlib.sha256(content).hexdigest())


def read_toml_snapshot(path: Path) -> tuple[dict[str, Any], ConfigurationSource]:
    """解析 TOML 并保留其来源快照。"""
    content, source = read_source(path)
    try:
        return tomllib.loads(content.decode("utf-8")), source
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(f"invalid TOML in {path}: {error}") from error
