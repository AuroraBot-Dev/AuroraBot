"""基于 loguru 的统一线程安全日志配置。"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger as _loguru_logger

_loguru_logger.remove()

if TYPE_CHECKING:
    from loguru import Logger, Record

MAX_LOGFILE_SIZE = 102400
MAX_LOGFILE_BACKUPS = 5
_NAME_WIDTH = 24
_LEVEL_NUMBERS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
_OFF_LEVEL = 51


class LogLevel(StrEnum):
    """进程与平台日志级别；NONE 表示不启用日志。"""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    NONE = "NONE"


class UnsupportedLoggingLevelError(ValueError): ...


@dataclass(slots=True)
class _Sink:
    """一个已注册 loguru sink 的句柄与生效级别。"""

    handle: int
    level: int
    path: Path | None = None


@dataclass(slots=True)
class _LoggingState:
    console_level: int = 20
    file_level: int = 20
    console_enabled: bool = True
    logfile: Path | None = None
    console: _Sink | None = None
    file: _Sink | None = None


_state = _LoggingState()
_lock = threading.Lock()


def get_logger(
    name: str | None = None,
    level: int | str | None = None,
    logfile: str | Path | None = None,
) -> Logger:
    """取得绑定模块名的 loguru Logger，输出跟随全局 sink 配置。"""
    logger_name = name or __package__ or "aurora"
    if level is not None:
        configure_logging(level, logfile)
    elif logfile is not None:
        configure_logging(_state.file_level, logfile)
    with _lock:
        _configure_sinks()
    return _loguru_logger.bind(name=logger_name)


def configure_logging(level: int | str, logfile: str | Path | None = None) -> None:
    """更新后续和既有 Logger 的级别与可选轮转文件。"""
    normalized = _level_number(level)
    with _lock:
        _state.console_level = normalized
        _state.file_level = normalized
        if logfile is not None:
            _state.logfile = Path(logfile)
        _configure_sinks()


def configure_console_logging(*, enabled: bool | None = None, level: int | str | None = None) -> None:
    """单独调整终端日志，不改变文件日志级别。"""
    with _lock:
        if enabled is not None:
            _state.console_enabled = enabled
        if level is not None:
            _state.console_level = _level_number(level)
        _configure_sinks()


def console_logging_status() -> dict[str, bool | str]:
    with _lock:
        return {
            "enabled": _state.console_enabled,
            "console_level": _level_name(_state.console_level),
            "file_level": _level_name(_state.file_level),
        }


def _configure_sinks() -> None:
    """在锁内对齐 console 与轮转文件 sink，使其与状态一致。"""
    console_level = _state.console_level if _state.console_enabled else _OFF_LEVEL
    if _state.console is None or _state.console.level != console_level:
        _replace_console(console_level)
    if _state.logfile is not None:
        file = _state.file
        if file is None or file.level != _state.file_level or file.path != _state.logfile:
            if file is not None:
                _loguru_logger.remove(file.handle)
                _state.file = None
            _state.logfile.parent.mkdir(parents=True, exist_ok=True)
            _state.file = _Sink(
                _loguru_logger.add(
                    str(_state.logfile),
                    format=_format_file,
                    level=_state.file_level,
                    encoding="utf-8",
                    rotation=MAX_LOGFILE_SIZE,
                    retention=MAX_LOGFILE_BACKUPS,
                ),
                _state.file_level,
                _state.logfile,
            )
    elif _state.file is not None:
        _loguru_logger.remove(_state.file.handle)
        _state.file = None


def _replace_console(level: int) -> None:
    if _state.console is not None:
        _loguru_logger.remove(_state.console.handle)
    _state.console = _Sink(
        _loguru_logger.add(sys.stderr, format=_format_console, level=level),
        level,
    )


def _format_console(record: Record) -> str:
    name = str(record["extra"].get("name", "aurora"))
    return f"<level>{{level: <8}}</level> <cyan>{name:<{_NAME_WIDTH}}</cyan> | {{message}}\n{{exception}}"


def _format_file(record: Record) -> str:
    name = str(record["extra"].get("name", "aurora"))
    return f"{{time:%m-%d %H:%M:%S}} {{level: <8}} {name:<{_NAME_WIDTH}} | {{message}}\n{{exception}}"


def _level_number(level: int | str | LogLevel) -> int:
    if isinstance(level, int):
        return level
    if isinstance(level, LogLevel):
        if level is LogLevel.NONE:
            return _OFF_LEVEL
        normalized = level.value
    else:
        normalized = "WARNING" if level.upper() == "WARN" else level.upper()
    value = _LEVEL_NUMBERS.get(normalized)
    if value is None:
        raise UnsupportedLoggingLevelError(level)
    return value


def _level_name(number: int) -> str:
    return next((name.lower() for name, value in _LEVEL_NUMBERS.items() if value == number), "unknown")
