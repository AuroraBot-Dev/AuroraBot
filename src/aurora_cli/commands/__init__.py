"""内置命令插件；每个命令包导出 MODULE，由统一 CLI 加载器发现。"""

from aurora_cli.contracts.command import CommandSpec, SubcommandSpec

__all__ = ["CommandSpec", "SubcommandSpec"]
