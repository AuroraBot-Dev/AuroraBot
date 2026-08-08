"""``/status`` 运行时命令的实现。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.contracts import CommandResult

if TYPE_CHECKING:
    import argparse

    from src.contracts.event import CommandContext

NAMES = ("/status",)
USAGE = "/status"
DESCRIPTION = "显示本地运行器状态"


def configure(_parser: argparse.ArgumentParser) -> None:
    """/status 无需额外参数。"""


async def handle(context: CommandContext, _arguments: argparse.Namespace) -> CommandResult:
    """拼装 profile、workspace 与运行时状态快照并以 JSON 返回。"""
    data = {
        "profile": context.runtime.configuration.runtime.profile,
        "workspace": str(context.runtime.configuration.engine.workspace),
        **context.runtime.status(),
    }
    return CommandResult(ok=True, text=json.dumps(data, ensure_ascii=False), data=data)
