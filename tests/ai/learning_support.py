"""复用的离线场景构造与替身，不依赖测试用例模块。"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from aurora_bot.mcp.config import PlatformsConfig
from aurora_bot.memory_model.config import MemoryModelConfig
from aurora_bot.rhythm.config import RhythmConfig
from aurora_cli import load_config
from aurora_cli.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora_cli.configs.memory_model import CONFIG_SPEC as MEMORY_MODEL_CONFIG
from aurora_cli.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG
from aurora_cli.configs.rhythm import CONFIG_SPEC as RHYTHM_CONFIG

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_cli import AuroraConfig


def _config(project: Path, domain: str, *, weights: str | None = None, ref: str | None = None) -> AuroraConfig:
    """只启用待验证模型，外部平台和自动认知明确禁用。"""
    config = load_config(project)
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    config = config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )
    if domain == "memory":
        return config.with_value(
            MEMORY_MODEL_CONFIG, MemoryModelConfig("aurora:memory/model/tgn", weights=weights, weights_ref=ref)
        )
    return config.with_value(RHYTHM_CONFIG, RhythmConfig("aurora:rhythm/model/gru", weights=weights, weights_ref=ref))
