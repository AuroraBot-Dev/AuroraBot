"""注册 ``config/logging.toml``。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import TomlTable, load_toml, table, text

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector

_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_WINDOWS_ABSOLUTE_MIN_LENGTH = 3


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
        _validate_relative_directory(self.log_dir)


LOGGING_CONFIG = ConfigKey[LoggingConfig]("logging")


def register(configs: ConfigCollector) -> None:
    configs.register(LOGGING_CONFIG, "config/logging.toml", _parse)


def _parse(path: Path) -> LoggingConfig:
    document = load_toml(path)
    _require_exact_fields(document, frozenset({"logging"}), "logging.toml")
    values = table(document, "logging")
    _require_exact_fields(values, frozenset({"level", "log_dir"}), "logging")
    return LoggingConfig(text(values, "level"), text(values, "log_dir"))


def _require_exact_fields(document: TomlTable, expected: frozenset[str], label: str) -> None:
    names = set(document)
    if names != expected:
        raise ValueError(f"{label} 字段不匹配：未知 {sorted(names - expected)}，缺少 {sorted(expected - names)}")


def _validate_relative_directory(value: str) -> None:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    windows_absolute = (
        len(normalized) >= _WINDOWS_ABSOLUTE_MIN_LENGTH and normalized[0].isalpha() and normalized[1:3] == ":/"
    )
    if not value.strip() or "\x00" in value or path.is_absolute() or windows_absolute or ".." in path.parts:
        raise ValueError("logging.log_dir 必须是项目内相对目录")


__all__ = ["LOGGING_CONFIG", "LoggingConfig", "register"]
