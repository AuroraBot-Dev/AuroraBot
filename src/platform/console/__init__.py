"""Console 平台公开 API。"""

from src.platform.console.adapter import (
    CONSOLE_SEND_CAPABILITY,
    CONSOLE_SEND_DESCRIPTOR,
    ConsolePlatform,
)

__all__ = [
    "CONSOLE_SEND_CAPABILITY",
    "CONSOLE_SEND_DESCRIPTOR",
    "ConsolePlatform",
]
