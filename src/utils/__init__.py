"""无外部依赖的通用工具集：日志、JSON 提取、文本装配、时间与 uvicorn 辅助。"""

from src.utils.logging import (
    UnsupportedLoggingLevelError,
    configure_console_logging,
    configure_logging,
    console_logging_status,
    get_logger,
)
from src.utils.serialization import extract_json_from_text
from src.utils.text import bounded_summary
from src.utils.time import utc_now, utc_today
from src.utils.uvicorn import LifespanSafeApp, SignalSafeServer

__all__ = [
    "LifespanSafeApp",
    "SignalSafeServer",
    "UnsupportedLoggingLevelError",
    "bounded_summary",
    "configure_console_logging",
    "configure_logging",
    "console_logging_status",
    "extract_json_from_text",
    "get_logger",
    "utc_now",
    "utc_today",
]
