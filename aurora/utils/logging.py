"""应用项目日志配置：终端与轮转文件 sink。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.configuration.runtime import RUNTIME_CONFIG
from aurora.configuration.storage import STORAGE_CONFIG, resolve_directory
from src.utils import configure_console_logging, configure_logging

if TYPE_CHECKING:
    from aurora.config import AuroraConfig


def configure_project_logging(config: AuroraConfig) -> None:
    """在其他运行时效果前应用项目日志配置。"""
    runtime = config.get(RUNTIME_CONFIG)
    logfile = config.project_root / resolve_directory(config.get(STORAGE_CONFIG).entries, "logs") / "aurora.log"
    configure_console_logging(enabled=True, level=runtime.log_level)
    configure_logging(runtime.log_level, logfile)
