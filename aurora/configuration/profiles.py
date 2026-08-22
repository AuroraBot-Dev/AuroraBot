"""注册 ``config/profiles.toml`` 的环境 profile 配置。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import load_toml, table, text

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class ProfilesConfig:
    profiles: dict[str, str]


PROFILES_CONFIG = ConfigKey[ProfilesConfig]("profiles")


def register(configs: ConfigCollector) -> None:
    configs.register(PROFILES_CONFIG, "config/profiles.toml", _parse)


def _parse(path: Path) -> ProfilesConfig:
    root = load_toml(path)
    profiles: dict[str, str] = {}
    for section in ("dev", "prod"):
        section_table = table(root, section)
        profiles[section] = text(section_table, "profile")
    return ProfilesConfig(profiles)
