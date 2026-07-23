"""``/agent`` 运行时命令的实现。"""

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
    """配置 /agent 命令的命令行参数。"""
    parser.add_argument("agent_id")


async def handle(context: CommandContext, arguments: argparse.Namespace) -> CommandResult:
    """查询指定 Agent 详情并以 JSON 格式返回。"""
    agent = context.runtime.agent(arguments.agent_id)
    if agent is None:
        return CommandResult(ok=False, text="Agent 不存在")
    return CommandResult(ok=True, text=json.dumps(agent, ensure_ascii=False, indent=2), data=agent)
