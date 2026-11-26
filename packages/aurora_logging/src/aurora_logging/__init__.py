"""由进程入口显式配置的终端与轮转文件日志。"""

import logging
from copy import copy
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

__all__ = ["configure_logging"]

_handlers: list[logging.Handler] = []


class _ConsoleFilter(logging.Filter):
    def __init__(self, tracebacks: bool) -> None:
        super().__init__()
        self.tracebacks = tracebacks

    def filter(self, record: logging.LogRecord) -> logging.LogRecord:
        # 终端的异常展示策略只作用于副本，文件始终保留完整异常。
        record = copy(record)
        if not self.tracebacks:
            record.exc_info = None
            record.exc_text = None
        return record


def configure_logging(
    *,
    log_dir: Path | None = None,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    console_tracebacks: bool = True,
) -> None:
    """配置 root logger；业务包直接使用标准库 getLogger(__name__)。

    入口在启动阶段调用，log_dir 为 None 时仅输出至 stderr。
    文件为 log_dir/aurora.log，使用 UTF-8 并按大小轮转。
    日志目录由单进程独占；重复调用替换并关闭本包的处理器，保留外部处理器。
    """
    if max_bytes <= 0 or backup_count <= 0:
        raise ValueError("日志轮转大小和保留数量必须为正数")
    if any(not isinstance(level, int) or level < 0 for level in (console_level, file_level)):
        raise ValueError("日志级别必须为非负整数")

    console = RichHandler(console=Console(stderr=True), rich_tracebacks=True, markup=False)
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter("%(message)s"))
    console.addFilter(_ConsoleFilter(console_tracebacks))
    handlers: list[logging.Handler] = [console]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file = RotatingFileHandler(
            log_dir / "aurora.log", maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file.setLevel(file_level)
        file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handlers.append(file)

    root = logging.getLogger()
    for handler in _handlers:
        root.removeHandler(handler)
        handler.close()
    _handlers[:] = handlers
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(min(handler.level for handler in handlers))
