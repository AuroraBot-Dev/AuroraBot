"""注册 ``config/extensions.toml``。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.config import ConfigKey, TomlDocument
from aurora.utils.toml import load_toml

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector

EXTENSIONS_CONFIG = ConfigKey[TomlDocument]("extensions")


def register(configs: ConfigCollector) -> None:
    configs.register(EXTENSIONS_CONFIG, "config/extensions.toml", _parse)


def _parse(path: Path) -> TomlDocument:
    return TomlDocument(load_toml(path))
