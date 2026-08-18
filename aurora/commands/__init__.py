"""CLI 命令目录；新增命令在此显式注册。"""

from aurora.commands import about, check, donk

COMMAND_REGISTRARS = (about.register, check.register, donk.register)

__all__ = ["COMMAND_REGISTRARS"]
