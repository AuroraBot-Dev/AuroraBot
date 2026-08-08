"""``/event`` AMP 注入命令的实现。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.contracts import (
    CommandResult,
    new_amp,
)

if TYPE_CHECKING:
    import argparse

    from src.contracts.event import CommandContext

NAMES = ("/event", "/e")
USAGE = "/event <type> [--source APP] [--session ID] [--summary TEXT] [--data JSON]"
DESCRIPTION = "投递任意 AMP 事件"


def configure(parser: argparse.ArgumentParser) -> None:
    """配置 /event 命令参数：事件类型、来源、会话、摘要与数据。"""
    parser.add_argument("event_type")
    parser.add_argument("--source")
    parser.add_argument("--session")
    parser.add_argument("--summary", default="Runtime command event")
    parser.add_argument("--data", default="{}")


async def handle(context: CommandContext, arguments: argparse.Namespace) -> CommandResult:
    """构建并提交自定义 AMP 事件到 engine 邮箱。"""
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
    message_id = await context.runtime.submit_amp(amp.to_dict())
    return CommandResult(ok=True, text=f"已投递 AMP: {message_id}", message_id=message_id)
