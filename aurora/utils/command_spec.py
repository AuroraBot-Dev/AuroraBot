"""CLI COMMAND 规格字典的类型约束；纯类型声明，不包含注册逻辑。

顶层命令用 CommandSpec（必须提供 name），子命令用 SubcommandSpec；
options 值为帮助文本（布尔开关），也可用字典完整透传 add_argument 关键字。
"""

from __future__ import annotations

from typing import Any, Required, TypedDict


class SubcommandSpec(TypedDict, total=False):
    help: str
    options: dict[str, str | dict[str, Any]]
    args: dict[str, str]
    subcommands: dict[str, SubcommandSpec]


class CommandSpec(SubcommandSpec):
    name: Required[str]
