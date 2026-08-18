"""注册 ``config/logging.toml``。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.config import ConfigKey, TomlDocument
from aurora.utils.toml import load_toml

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector

LOGGING_CONFIG = ConfigKey[TomlDocument]("logging")


def register(configs: ConfigCollector) -> None:
    configs.register(LOGGING_CONFIG, "config/logging.toml", _parse)


def _parse(path: Path) -> TomlDocument:
    return TomlDocument(load_toml(path))
