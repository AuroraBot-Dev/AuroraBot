"""注册 ``config/logging.toml``。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import check_relative_directory, load_toml, require_exact_fields, table, text

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector

_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    """进程终端与轮转文件日志的纯配置。"""

    level: str
    log_dir: str

    def __post_init__(self) -> None:
        normalized = "WARNING" if self.level.upper() == "WARN" else self.level.upper()
        if normalized not in _LEVELS:
            raise ValueError("logging.level 必须是 DEBUG/INFO/WARNING/ERROR/CRITICAL")
        object.__setattr__(self, "level", normalized)
        check_relative_directory(self.log_dir, "logging.log_dir")


LOGGING_CONFIG = ConfigKey[LoggingConfig]("logging")


def register(configs: ConfigCollector) -> None:
    configs.register(LOGGING_CONFIG, "config/logging.toml", _parse)


def _parse(path: Path) -> LoggingConfig:
    document = load_toml(path)
    require_exact_fields(document, frozenset({"logging"}), "logging.toml")
    values = table(document, "logging")
    require_exact_fields(values, frozenset({"level", "log_dir"}), "logging")
    return LoggingConfig(text(values, "level"), text(values, "log_dir"))


__all__ = ["LOGGING_CONFIG", "LoggingConfig", "register"]
