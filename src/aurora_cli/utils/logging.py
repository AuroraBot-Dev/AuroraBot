"""应用项目日志配置：终端与轮转文件 sink。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_bot.utils import configure_console_logging, configure_logging
from aurora_cli.configs.runtime import CONFIG_SPEC as RUNTIME_CONFIG

if TYPE_CHECKING:
    from aurora_cli.contracts.config import AuroraConfig


def configure_project_logging(config: AuroraConfig) -> None:
    """在其他运行时效果前应用项目日志配置。"""
    from aurora_bot.world.config import resolve_storage_directory
    from aurora_cli.configs.storage import CONFIG_SPEC as STORAGE_CONFIG

    runtime = config.get(RUNTIME_CONFIG)
    logfile = config.project_root / resolve_storage_directory(config.get(STORAGE_CONFIG).entries, "logs") / "aurora.log"
    configure_console_logging(enabled=True, level=runtime.log_level)
    configure_logging(runtime.log_level, logfile)
