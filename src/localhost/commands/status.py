"""Implementation of the ``/status`` runtime command."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.localhost.command_types import CommandResult

if TYPE_CHECKING:
    import argparse

    from src.localhost.command_types import CommandContext

NAMES = ("/status",)
USAGE = "/status"
DESCRIPTION = "显示本地运行器状态"


def configure(_parser: argparse.ArgumentParser) -> None:
    return None


async def handle(context: CommandContext, _arguments: argparse.Namespace) -> CommandResult:
    data = {
        "profile": context.runtime.configuration.runtime.profile,
        "workspace": str(context.runtime.configuration.runtime.workspace),
        **context.runtime.status(),
    }
    return CommandResult(ok=True, text=json.dumps(data, ensure_ascii=False), data=data)
