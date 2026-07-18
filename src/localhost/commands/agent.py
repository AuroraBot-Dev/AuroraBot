"""Implementation of the ``/agent`` runtime command."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.localhost.command_types import CommandResult

if TYPE_CHECKING:
    import argparse

    from src.localhost.command_types import CommandContext

NAMES = ("/agent",)
USAGE = "/agent <agent_id>"
DESCRIPTION = "查询 Agent 与邮箱"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("agent_id")


async def handle(context: CommandContext, arguments: argparse.Namespace) -> CommandResult:
    agent = context.runtime.agent(arguments.agent_id)
    if agent is None:
        return CommandResult(ok=False, text="Agent 不存在")
    return CommandResult(ok=True, text=json.dumps(agent, ensure_ascii=False, indent=2), data=agent)
