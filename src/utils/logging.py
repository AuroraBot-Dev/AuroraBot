"""日志系统核心模块。

提供统一的日志记录器工厂 ``get_logger()``，支持 Rich 美化控制台输出、文件轮转日志。

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

import logging
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 文件日志格式
FILE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s | %(message)s"

# 控制台格式
CONSOLE_FORMAT = "%(name)s | %(message)s"

# 日志时间格式
DATETIME_FORMAT = "%m-%d %H:%M:%S"

FILE_FORMATTER = logging.Formatter(FILE_FORMAT, DATETIME_FORMAT)
CONSOLE_FORMATTER = logging.Formatter(CONSOLE_FORMAT, DATETIME_FORMAT)

# 日志轮转配置
MAX_LOGFILE_SIZE = 102400
MAX_LOGFILE_BACKUPS = 5

# 日志级别
LOG_LEVEL: int | str = logging.INFO


@dataclass(slots=True)
class _LoggingState:
    console_level: int = logging.INFO
    file_level: int = logging.INFO
    console_enabled: bool = True
    logfile: Path | None = None


_logging_state = _LoggingState()
_managed_logger_names: set[str] = set()
_MANAGED_FILE_HANDLER = "_aurora_managed_file_handler"
_MANAGED_CONSOLE_HANDLER = "_aurora_managed_console_handler"
_EXTERNAL_CONSOLE_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
_OFF_LEVEL = logging.CRITICAL + 1
_TERMINAL_RECORD_ATTRIBUTE = "aurora_terminal"


class _TerminalVisibilityFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return bool(getattr(record, _TERMINAL_RECORD_ATTRIBUTE, True))


class UnsupportedLoggingLevelError(ValueError): ...


def _level_number(level: int | str) -> int:
    if isinstance(level, int):
        return level
    normalized = level.upper()
    if normalized == "WARN":
        normalized = "WARNING"
    value = logging.getLevelNamesMapping().get(normalized)
    if value is None:
        raise UnsupportedLoggingLevelError(level)
    return value


def _level_name(level: int) -> str:
    value = logging.getLevelName(level)
    return value if isinstance(value, str) else str(level)


def _create_stream_handler(
    level: int | str = LOG_LEVEL,
    formatter: logging.Formatter = CONSOLE_FORMATTER,
) -> logging.Handler:
    # 控制台使用 Rich 美化输出；降级到纯文本 StreamHandler 当 rich 不可用时
    try:
        from rich.console import Console
        from rich.logging import RichHandler
        from rich.theme import Theme

        class _BracketRichHandler(RichHandler):
            """在 Rich 渲染前给 levelname 加方括号，保持控制台日志紧凑。"""

            def emit(self, record: logging.LogRecord) -> None:
                original = record.levelname
                record.levelname = f"[{original}]"
                try:
                    super().emit(record)
                finally:
                    record.levelname = original

        theme = Theme(
            {
                "log.time": "green",
                "logging.level.debug": "cyan",
                "logging.level.info": "white",
                "logging.level.warning": "yellow",
                "logging.level.error": "bold red",
                "logging.level.critical": "bold white on red",
                "logging.level.[debug]": "cyan",
                "logging.level.[info]": "white",
                "logging.level.[warning]": "yellow",
                "logging.level.[error]": "bold red",
                "logging.level.[critical]": "bold white on red",
            }
        )
        console = Console(theme=theme, stderr=True)
        rh = _BracketRichHandler(
            console=console,
            level=level,
            show_time=True,
            omit_repeated_times=False,
            show_level=True,
            show_path=False,
            markup=False,
            rich_tracebacks=True,
            tracebacks_show_locals=False,
        )
        rh.setFormatter(formatter)
        rh.addFilter(_TerminalVisibilityFilter())
        setattr(rh, _MANAGED_CONSOLE_HANDLER, True)
        return rh  # noqa: TRY300
    except ImportError:
        sh = logging.StreamHandler()
        sh.setLevel(level)
        sh.setFormatter(formatter)
        sh.addFilter(_TerminalVisibilityFilter())
        setattr(sh, _MANAGED_CONSOLE_HANDLER, True)
        return sh


def _create_file_handler(
    logfile: str | Path,
    level: int | str = LOG_LEVEL,
    formatter: logging.Formatter = FILE_FORMATTER,
) -> logging.Handler:
    # 使用大小轮转日志文件
    Path(logfile).parent.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(
        logfile,
        maxBytes=MAX_LOGFILE_SIZE,
        backupCount=MAX_LOGFILE_BACKUPS,
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(formatter)
    return fh


def get_logger(
    name: str | None = None,
    level: int | str | None = None,
    logfile: str | Path | None = None,
) -> logging.Logger:
    """
    返回配置好的日志记录器
    - name: 日志记录器名称 (默认根记录器) .
    - level: 日志级别 (默认从配置文件中获取) .
    - logfile: 日志文件路径；未显式配置时只写控制台。
    """
    if name is None:
        # 默认使用根包名, 如果无法获取则使用"Default"
        name = __package__ or "Default"

    console_level = _logging_state.console_level if level is None else _level_number(level)
    file_level = _logging_state.file_level if level is None else _level_number(level)
    _managed_logger_names.add(name)

    logger = logging.getLogger(name)
    if logger.handlers:
        _apply_managed_logger(logger)
        return logger

    logger.setLevel(min(console_level, file_level))
    logger.propagate = False

    # 配置控制台输出
    stream_handler = _create_stream_handler(console_level)
    if not _logging_state.console_enabled:
        stream_handler.setLevel(_OFF_LEVEL)
    logger.addHandler(stream_handler)

    # 配置文件输出
    effective_logfile = logfile if logfile is not None else _logging_state.logfile
    if isinstance(effective_logfile, (str, Path)):
        file_handler = _create_file_handler(effective_logfile, file_level)
        setattr(file_handler, _MANAGED_FILE_HANDLER, True)
        logger.addHandler(file_handler)

    return logger


def _apply_managed_logger(logger: logging.Logger) -> None:
    """将当前的运行时日志快照应用到已存在的记录器。"""
    active_levels: list[int] = []
    for handler in logger.handlers:
        if getattr(handler, _MANAGED_CONSOLE_HANDLER, False):
            handler_level = _logging_state.console_level if _logging_state.console_enabled else _OFF_LEVEL
            handler.setLevel(handler_level)
            if _logging_state.console_enabled:
                active_levels.append(_logging_state.console_level)
        elif getattr(handler, _MANAGED_FILE_HANDLER, False):
            handler.setLevel(_logging_state.file_level)
            active_levels.append(_logging_state.file_level)
    logger.setLevel(min(active_levels, default=_OFF_LEVEL))


def _apply_external_console_state() -> None:
    """将当前的运行时日志快照应用到外部库的控制台记录器。"""
    level = _logging_state.console_level if _logging_state.console_enabled else _OFF_LEVEL
    for name in _EXTERNAL_CONSOLE_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        for handler in logger.handlers:
            if not getattr(handler, _MANAGED_FILE_HANDLER, False):
                handler.setLevel(level)


def configure_logging(level: int | str, logfile: str | Path | None = None) -> None:
    """将一份显式运行时日志快照应用到已有和后续创建的记录器。"""
    normalized = _level_number(level)
    _logging_state.console_level = normalized
    _logging_state.file_level = normalized
    _logging_state.console_enabled = True
    if logfile is not None:
        _logging_state.logfile = Path(logfile)
    for name in tuple(_managed_logger_names):
        logger = logging.getLogger(name)
        if logfile is not None:
            for handler in tuple(logger.handlers):
                if getattr(handler, _MANAGED_FILE_HANDLER, False):
                    logger.removeHandler(handler)
                    handler.close()
            file_handler = _create_file_handler(logfile, normalized)
            setattr(file_handler, _MANAGED_FILE_HANDLER, True)
            logger.addHandler(file_handler)
        _apply_managed_logger(logger)
    _apply_external_console_state()


def configure_console_logging(*, enabled: bool | None = None, level: int | str | None = None) -> None:
    """调整终端日志输出，不削弱已配置的文件审计日志。"""
    if enabled is not None:
        _logging_state.console_enabled = enabled
    if level is not None:
        _logging_state.console_level = _level_number(level)
    for name in tuple(_managed_logger_names):
        _apply_managed_logger(logging.getLogger(name))
    _apply_external_console_state()


def console_logging_status() -> dict[str, bool | str]:
    """返回当前的终端日志状态和持久化文件级别阈值。"""
    return {
        "enabled": _logging_state.console_enabled,
        "console_level": _level_name(_logging_state.console_level).lower(),
        "file_level": _level_name(_logging_state.file_level).lower(),
    }
