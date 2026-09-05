"""TOML 配置目录；新增配置在此显式注册。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.config import assemble_config
from aurora.configuration import (
    agents,
    apps,
    cadence,
    endpoints,
    engine,
    memory,
    platforms,
    prompts,
    providers,
    runtime,
    storage,
)

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import AuroraConfig

CONFIG_SPECS = (
    runtime.RUNTIME_CONFIG,
    engine.ENGINE_CONFIG,
    agents.AGENTS_CONFIG,
    providers.PROVIDERS_CONFIG,
    endpoints.ENDPOINTS_CONFIG,
    prompts.PROMPTS_CONFIG,
    apps.APPS_CONFIG,
    platforms.PLATFORMS_CONFIG,
    memory.MEMORY_CONFIG,
    storage.STORAGE_CONFIG,
    cadence.CADENCE_CONFIG,
)


def load_config(project_root: Path) -> AuroraConfig:
    return assemble_config(project_root, CONFIG_SPECS)


__all__ = ["CONFIG_SPECS", "load_config"]
