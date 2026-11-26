"""查看当前已登记的公共定义，不创建运行期资源。"""

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from ...declarations import CommandContext, command_plugin


def execute(context: CommandContext) -> None:
    table = Table("ID", "类型", "提供者", box=box.SIMPLE, show_edge=False)
    for entry in sorted(context.registry.entries(), key=lambda entry: str(entry.id)):
        table.add_row(Text(str(entry.id)), Text(entry.kind), Text(entry.provider))
    Console(file=context.output).print(table)


def plugin():
    return command_plugin(
        __name__,
        {
            "id/list": {
                "help": "列出启动前已登记的公共 ID、类型和提供者，不启动装配",
                "executor": execute,
            }
        },
    )
