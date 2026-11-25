"""显示当前接收的命令及其完整身份。"""

from collections.abc import Iterable
from typing import TextIO

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .declarations import Command


def show_commands(commands: Iterable[Command], output: TextIO) -> None:
    table = Table("命令 ID", "用途", box=box.SIMPLE, show_edge=False)
    for item in commands:
        table.add_row(Text(str(item.id)), Text(item.help))
    Console(file=output).print(table)
