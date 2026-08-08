"""``/task`` 运行时命令的实现。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.contracts import CommandResult

if TYPE_CHECKING:
    import argparse

    from src.contracts.event import CommandContext

NAMES = ("/task",)
USAGE = "/task <task_id>"
DESCRIPTION = "查询 Task 与监督树"


def configure(parser: argparse.ArgumentParser) -> None:
    """配置 /task 命令的参数：Task ID。"""
    parser.add_argument("task_id")


async def handle(context: CommandContext, arguments: argparse.Namespace) -> CommandResult:
    """查询指定 Task 详情并以 JSON 格式返回。"""
    task = context.runtime.task(arguments.task_id)
    if task is None:
        return CommandResult(ok=False, text="Task 不存在")
    return CommandResult(ok=True, text=json.dumps(task, ensure_ascii=False, indent=2), data=task)
