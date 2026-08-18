"""基于标准库的统一日志配置。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

FILE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s | %(message)s"
CONSOLE_FORMAT = "%(levelname)s %(name)s | %(message)s"
DATETIME_FORMAT = "%m-%d %H:%M:%S"
MAX_LOGFILE_SIZE = 102400
MAX_LOGFILE_BACKUPS = 5
_FILE_HANDLER = "_aurora_file_handler"
_CONSOLE_HANDLER = "_aurora_console_handler"
_OFF_LEVEL = logging.CRITICAL + 1


class UnsupportedLoggingLevelError(ValueError): ...


@dataclass(slots=True)
class _LoggingState:
    console_level: int = logging.INFO
    file_level: int = logging.INFO
    console_enabled: bool = True
    logfile: Path | None = None


_state = _LoggingState()
_logger_names: set[str] = set()


def get_logger(
    name: str | None = None,
    level: int | str | None = None,
    logfile: str | Path | None = None,
) -> logging.Logger:
    """取得由 AuroraBot 统一管理的非传播 Logger。"""
    logger_name = name or __package__ or "aurora"
    _logger_names.add(logger_name)
    logger = logging.getLogger(logger_name)
    logger.propagate = False
    if not logger.handlers:
        console = logging.StreamHandler()
        setattr(console, _CONSOLE_HANDLER, True)
        console.setFormatter(logging.Formatter(CONSOLE_FORMAT, DATETIME_FORMAT))
        logger.addHandler(console)
    if logfile is not None:
        _state.logfile = Path(logfile)
    if level is not None:
        normalized = _level_number(level)
        _state.console_level = normalized
        _state.file_level = normalized
    _apply(logger)
    return logger


def configure_logging(level: int | str, logfile: str | Path | None = None) -> None:
    """更新后续和既有 Logger 的级别与可选轮转文件。"""
    normalized = _level_number(level)
    _state.console_level = normalized
    _state.file_level = normalized
    if logfile is not None:
        _state.logfile = Path(logfile)
    for name in tuple(_logger_names):
        _apply(logging.getLogger(name), rebuild_file=logfile is not None)


def configure_console_logging(*, enabled: bool | None = None, level: int | str | None = None) -> None:
    """单独调整终端日志，不改变文件日志级别。"""
    if enabled is not None:
        _state.console_enabled = enabled
    if level is not None:
        _state.console_level = _level_number(level)
    for name in tuple(_logger_names):
        _apply(logging.getLogger(name))


def console_logging_status() -> dict[str, bool | str]:
    return {
        "enabled": _state.console_enabled,
        "console_level": logging.getLevelName(_state.console_level).lower(),
        "file_level": logging.getLevelName(_state.file_level).lower(),
    }


def _apply(logger: logging.Logger, *, rebuild_file: bool = False) -> None:
    if rebuild_file:
        for handler in tuple(logger.handlers):
            if getattr(handler, _FILE_HANDLER, False):
                logger.removeHandler(handler)
                handler.close()
    if _state.logfile is not None and not any(getattr(item, _FILE_HANDLER, False) for item in logger.handlers):
        _state.logfile.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            _state.logfile,
            maxBytes=MAX_LOGFILE_SIZE,
            backupCount=MAX_LOGFILE_BACKUPS,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(FILE_FORMAT, DATETIME_FORMAT))
        setattr(file_handler, _FILE_HANDLER, True)
        logger.addHandler(file_handler)
    active: list[int] = []
    for handler in logger.handlers:
        if getattr(handler, _CONSOLE_HANDLER, False):
            handler.setLevel(_state.console_level if _state.console_enabled else _OFF_LEVEL)
            if _state.console_enabled:
                active.append(_state.console_level)
        elif getattr(handler, _FILE_HANDLER, False):
            handler.setLevel(_state.file_level)
            active.append(_state.file_level)
    logger.setLevel(min(active, default=_OFF_LEVEL))


def _level_number(level: int | str) -> int:
    if isinstance(level, int):
        return level
    normalized = "WARNING" if level.upper() == "WARN" else level.upper()
    value = logging.getLevelNamesMapping().get(normalized)
    if value is None:
        raise UnsupportedLoggingLevelError(level)
    return value
