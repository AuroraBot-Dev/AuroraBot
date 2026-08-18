"""注册 ``config/profiles/prod.toml``。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.config import ConfigKey, TomlDocument
from aurora.utils.toml import load_toml

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector

PROD_PROFILE_CONFIG = ConfigKey[TomlDocument]("profiles.prod")


def register(configs: ConfigCollector) -> None:
    configs.register(PROD_PROFILE_CONFIG, "config/profiles/prod.toml", _parse)


def _parse(path: Path) -> TomlDocument:
    return TomlDocument(load_toml(path))
