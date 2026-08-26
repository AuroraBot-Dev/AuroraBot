"""CLI 命令目录；新增命令在此显式注册。"""

from aurora.commands import (
    about,
    check,
    config,
    donk,
    setup,
    start,
)

COMMAND_REGISTRARS = (
    start.register,
    about.register,
    check.register,
    config.register,
    donk.register,
    setup.register,
)

__all__ = ["COMMAND_REGISTRARS"]
