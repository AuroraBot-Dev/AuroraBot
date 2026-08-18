"""注册 ``config/profiles/dev.toml``。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.config import ConfigKey, TomlDocument
from aurora.utils.toml import load_toml

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector

DEV_PROFILE_CONFIG = ConfigKey[TomlDocument]("profiles.dev")


def register(configs: ConfigCollector) -> None:
    configs.register(DEV_PROFILE_CONFIG, "config/profiles/dev.toml", _parse)


def _parse(path: Path) -> TomlDocument:
    return TomlDocument(load_toml(path))
