"""帮助命令的声明与执行入口。"""

from ...declarations import CommandContext, command_plugin
from ...presentation import show_commands as execute


def dispatch(context: CommandContext) -> None:
    execute(context.commands, context.output)


def plugin():
    return command_plugin(__name__, {"help": {"help": "列出当前可用命令", "executor": dispatch}})
