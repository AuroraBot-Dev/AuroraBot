"""CLI 交互和演示共用的命令声明。"""

from aurora_cli.contracts.command import CommandSpec

COMMAND: CommandSpec = {
    "name": "demo",
    "help": "演示参数解析和命令分派",
    "subcommands": {
        "greet": {
            "help": "向指定对象问候",
            "args": {"name": "称呼"},
            "options": {"--uppercase": "将称呼转换为大写"},
        },
        "forward": {"help": "查看透传参数", "passthrough": "传给目标程序的参数"},
    },
}
