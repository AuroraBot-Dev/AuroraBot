"""TOML 配置目录；新增配置在此显式注册。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.config import collect_config
from aurora.configuration import (
    agents,
    apps,
    engine,
    extensions,
    logging,
    models,
    platforms,
    prompts,
    runtime,
    storage,
)
from aurora.configuration.profiles import dev, prod

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import AuroraConfig

CONFIG_REGISTRARS = (
    runtime.register,
    engine.register,
    agents.register,
    models.register,
    prompts.register,
    apps.register,
    platforms.register,
    extensions.register,
    logging.register,
    storage.register,
    dev.register,
    prod.register,
)


def load_config(project_root: Path) -> AuroraConfig:
    return collect_config(project_root, CONFIG_REGISTRARS)


__all__ = ["CONFIG_REGISTRARS", "load_config"]
