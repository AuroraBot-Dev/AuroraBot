"""注册 ``config/storage.toml``。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.config import ConfigKey, TomlDocument
from aurora.utils.toml import load_toml

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector

STORAGE_CONFIG = ConfigKey[TomlDocument]("storage")


def register(configs: ConfigCollector) -> None:
    configs.register(STORAGE_CONFIG, "config/storage.toml", _parse)


def _parse(path: Path) -> TomlDocument:
    return TomlDocument(load_toml(path))
