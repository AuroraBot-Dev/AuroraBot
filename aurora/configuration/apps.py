"""注册 ``config/apps.toml``。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.config import ConfigKey, TomlDocument
from aurora.utils.toml import load_toml

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector

APPS_CONFIG = ConfigKey[TomlDocument]("apps")


def register(configs: ConfigCollector) -> None:
    configs.register(APPS_CONFIG, "config/apps.toml", _parse)


def _parse(path: Path) -> TomlDocument:
    return TomlDocument(load_toml(path))
