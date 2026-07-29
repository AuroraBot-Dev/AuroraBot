"""/reload`` 运行时命令的实现 — 重新加载 TOML 配置。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.config import reload as reload_config
from src.contracts.event import CommandResult

if TYPE_CHECKING:
    import argparse

    from src.contracts.event import CommandContext

NAMES = ("/reload",)
USAGE = "/reload"
DESCRIPTION = "从磁盘重新加载全部 TOML 配置并通知订阅者"


def configure(_parser: argparse.ArgumentParser) -> None:
    """/reload 无需额外参数。"""


async def handle(context: CommandContext, _arguments: argparse.Namespace) -> CommandResult:
    """重新加载配置快照并返回新配置摘要。"""
    new_config = reload_config()
    data = {
        "profile": new_config.runtime.profile,
        "workspace": str(new_config.engine.workspace),
        "platforms": [name for name in ("console", "dashboard", "mcp") if getattr(new_config.preference, name).enabled],
        **context.runtime.status(),
    }
    return CommandResult(ok=True, text=json.dumps(data, ensure_ascii=False), data=data)
