"""日志系统核心模块。

提供统一的日志记录器工厂 ``get_logger()``，支持 Rich 美化控制台输出、
文件轮转日志、以及 ``DecoratorFactory`` 装饰器注入。

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

import functools
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, cast

try:
    from concurrent_log_handler import ConcurrentRotatingFileHandler
except Exception:  # noqa: BLE001 — 回退到标准 RotatingFileHandler 永远安全
    # ModuleNotFoundError（未安装）、FileNotFoundError（Reasonix 沙箱残留 TMP 环境变量）
    # 或其他环境问题导致无法加载时，回退到标准 RotatingFileHandler
    ConcurrentRotatingFileHandler = RotatingFileHandler


# 文件日志格式
FILE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s | %(message)s"

# 控制台格式
CONSOLE_FORMAT = "%(name)s | %(message)s"

# 日志时间格式
DATETIME_FORMAT = "%m-%d %H:%M:%S"

FILE_FORMATTER = logging.Formatter(FILE_FORMAT, DATETIME_FORMAT)
CONSOLE_FORMATTER = logging.Formatter(CONSOLE_FORMAT, DATETIME_FORMAT)

# 日志轮转配置
MAX_LOGFILE_SIZE = 102400  # KB
MAX_LOGFILE_BACKUPS = 5  # 保留5个备份

# 日志级别
LOG_LEVEL: int | str = logging.INFO


@dataclass(slots=True)
class _LoggingState:
    level: int | str = LOG_LEVEL
    logfile: Path | None = None


_logging_state = _LoggingState()
_managed_logger_names: set[str] = set()
_MANAGED_FILE_HANDLER = "_aurora_managed_file_handler"


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
                # 不带括号 — Rich 默认 key
                "logging.level.debug": "cyan",
                "logging.level.info": "white",
                "logging.level.warning": "yellow",
                "logging.level.error": "bold red",
                "logging.level.critical": "bold white on red",
                # 带括号 — _BracketRichHandler 改写 levelname 后对应的 key
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
        return rh  # noqa: TRY300
    except ImportError:
        sh = logging.StreamHandler()
        sh.setLevel(level)
        sh.setFormatter(formatter)
        return sh


def _create_file_handler(
    logfile: str | Path,
    level: int | str = LOG_LEVEL,
    formatter: logging.Formatter = FILE_FORMATTER,
) -> logging.Handler:
    # 使用大小轮转日志文件, 每个文件最大100KB, 保留5个备份
    Path(logfile).parent.mkdir(parents=True, exist_ok=True)
    fh = ConcurrentRotatingFileHandler(
        logfile,
        maxBytes=MAX_LOGFILE_SIZE,
        backupCount=MAX_LOGFILE_BACKUPS,
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(formatter)
    return fh


class DecoratorFactory:
    """
    一个工厂类, 用于创建日志装饰器, 并将其绑定到指定的日志记录器实例.
    例如, @logger.decorate.info("Executing {func_name}")
    """

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _create_decorator(
        self, level: int, message_template: str
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                # 绑定参数到函数签名, 并应用默认值
                bound_args = inspect.signature(func).bind(*args, **kwargs)
                bound_args.apply_defaults()

                # 获取所有参数, 包括默认值
                all_args = bound_args.arguments

                # 创建格式化字典, 包含所有参数, 以及函数名, 参数列表, 关键字参数列表
                format_dict = {
                    **all_args,
                    "func_name": func.__name__,
                    "args": args,
                    "kwargs": kwargs,
                }

                self._logger.log(level, message_template.format(*args, **format_dict))
                return func(*args, **kwargs)

            return wrapper

        return decorator

    def info(self, message_template: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """创建一个 INFO 级别的日志装饰器, 用于记录函数调用前的信息."""
        return self._create_decorator(logging.INFO, message_template)

    def debug(self, message_template: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """创建一个 DEBUG 级别的日志装饰器, 用于记录函数调用前的调试信息."""
        return self._create_decorator(logging.DEBUG, message_template)

    def warning(self, message_template: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """创建一个 WARNING 级别的日志装饰器, 用于记录函数调用前的警告信息."""
        return self._create_decorator(logging.WARNING, message_template)

    def error(self, message_template: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """创建一个 ERROR 级别的日志装饰器, 用于记录函数调用前的错误信息."""
        return self._create_decorator(logging.ERROR, message_template)

    def exception(self, message_template: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """创建一个 ERROR 级别的日志装饰器，记录函数调用异常并附带堆栈."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                bound_args = inspect.signature(func).bind(*args, **kwargs)
                bound_args.apply_defaults()
                all_args = bound_args.arguments
                format_dict = {
                    **all_args,
                    "func_name": func.__name__,
                    "args": args,
                    "kwargs": kwargs,
                }
                try:
                    return func(*args, **kwargs)
                except Exception:
                    self._logger.exception(message_template.format(*args, **format_dict))
                    raise

            return wrapper

        return decorator


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

    effective_level = _logging_state.level if level is None else level
    _managed_logger_names.add(name)

    logger = logging.getLogger(name)
    if logger.handlers:
        logger.setLevel(effective_level)
        for handler in logger.handlers:
            handler.setLevel(effective_level)
        if not hasattr(logger, "decorate"):
            cast("Any", logger).decorate = DecoratorFactory(logger)
        return logger

    effective_logfile = logfile if logfile is not None else _logging_state.logfile

    logger.setLevel(effective_level)
    logger.propagate = False

    # 配置控制台输出
    logger.addHandler(_create_stream_handler(effective_level))

    if isinstance(effective_logfile, (str, Path)):
        file_handler = _create_file_handler(effective_logfile, effective_level)
        setattr(file_handler, _MANAGED_FILE_HANDLER, True)
        logger.addHandler(file_handler)

    # 将 DecoratorFactory 实例绑定到记录器, 用于创建日志装饰器
    cast("Any", logger).decorate = DecoratorFactory(logger)

    return logger


def configure_logging(level: int | str, logfile: str | Path | None = None) -> None:
    """Apply one explicit runtime logging snapshot to existing and future loggers."""
    _logging_state.level = level
    if logfile is not None:
        _logging_state.logfile = Path(logfile)
    for name in tuple(_managed_logger_names):
        logger = logging.getLogger(name)
        logger.setLevel(level)
        for handler in logger.handlers:
            handler.setLevel(level)
        if logfile is not None:
            for handler in tuple(logger.handlers):
                if getattr(handler, _MANAGED_FILE_HANDLER, False):
                    logger.removeHandler(handler)
                    handler.close()
            file_handler = _create_file_handler(logfile, level)
            setattr(file_handler, _MANAGED_FILE_HANDLER, True)
            logger.addHandler(file_handler)
