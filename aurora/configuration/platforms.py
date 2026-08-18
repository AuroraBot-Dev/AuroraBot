"""注册 ``config/platforms.toml``。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.config import ConfigKey, TomlDocument
from aurora.utils.toml import load_toml

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector

PLATFORMS_CONFIG = ConfigKey[TomlDocument]("platforms")


def register(configs: ConfigCollector) -> None:
    configs.register(PLATFORMS_CONFIG, "config/platforms.toml", _parse)


def _parse(path: Path) -> TomlDocument:
    return TomlDocument(load_toml(path))
