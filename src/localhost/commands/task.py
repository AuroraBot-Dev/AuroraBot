"""Implementation of the ``/task`` runtime command."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.localhost.command_types import CommandResult

if TYPE_CHECKING:
    import argparse

    from src.localhost.command_types import CommandContext

NAMES = ("/task",)
USAGE = "/task <task_id>"
DESCRIPTION = "查询 Task 与监督树"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("task_id")


async def handle(context: CommandContext, arguments: argparse.Namespace) -> CommandResult:
    task = context.runtime.task(arguments.task_id)
    if task is None:
        return CommandResult(ok=False, text="Task 不存在")
    return CommandResult(ok=True, text=json.dumps(task, ensure_ascii=False, indent=2), data=task)
