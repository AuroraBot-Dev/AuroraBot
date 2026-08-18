"""TOML 配置目录；新增配置在此显式注册。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.config import collect_config
from aurora.configuration import engine, prompt, runtime

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import AuroraConfig

CONFIG_REGISTRARS = (runtime.register, engine.register, prompt.register)


def load_config(project_root: Path) -> AuroraConfig:
    return collect_config(project_root, CONFIG_REGISTRARS)


__all__ = ["CONFIG_REGISTRARS", "load_config"]
