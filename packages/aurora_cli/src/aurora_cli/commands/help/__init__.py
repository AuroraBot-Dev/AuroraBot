"""帮助命令的声明与执行入口。"""

from ...declarations import CommandContext, builtin_commands
from ...presentation import show_commands as execute


def dispatch(context: CommandContext) -> None:
    execute(context.commands, context.output)


def plugin():
    return builtin_commands(__name__, {"help": dispatch})
