"""Implementation of the ``/event`` AMP injection command."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.contracts.amp import new_amp
from src.localhost.command_types import CommandResult

if TYPE_CHECKING:
    import argparse

    from src.localhost.command_types import CommandContext

NAMES = ("/event", "/e")
USAGE = "/event <type> [--source APP] [--session ID] [--summary TEXT] [--data JSON]"
DESCRIPTION = "投递任意 AMP 事件"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("event_type")
    parser.add_argument("--source")
    parser.add_argument("--session")
    parser.add_argument("--summary", default="Runtime command event")
    parser.add_argument("--data", default="{}")


async def handle(context: CommandContext, arguments: argparse.Namespace) -> CommandResult:
    try:
        data = json.loads(arguments.data)
    except json.JSONDecodeError as error:
        return CommandResult(ok=False, text=f"--data 不是有效 JSON: {error.msg}")
    if not isinstance(data, dict):
        return CommandResult(ok=False, text="--data 必须是 JSON object")
    amp = new_amp(
        event_type=arguments.event_type,
        session_id=arguments.session or context.request.session_id,
        summary=arguments.summary,
        data=data,
        source_app=arguments.source or context.request.source_app,
        source_instance=context.request.source_instance,
    )
    task_id = await context.runtime.submit_amp(amp.to_dict())
    return CommandResult(ok=True, text=f"已投递 AMP: {task_id}", task_id=task_id)
