"""``/ai`` 运行时命令：查询模型网关调用统计（RFC 0215）。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.contracts import CommandResult

if TYPE_CHECKING:
    import argparse

    from src.contracts.event import CommandContext

NAMES = ("/ai",)
USAGE = "/ai"
DESCRIPTION = "显示模型网关的调用费用与分类统计"


def configure(_parser: argparse.ArgumentParser) -> None:
    """/ai 无需额外参数。"""


async def handle(context: CommandContext, _arguments: argparse.Namespace) -> CommandResult:
    """查询 CostTracker 的总费用与角色/模型/状态分类统计。"""
    gateway = context.runtime.model_gateway
    if gateway is None or gateway.cost_tracker is None:
        return CommandResult(ok=False, text="model gateway is unavailable")
    tracker = gateway.cost_tracker
    data = {
        "total_cost": await tracker.total_cost(),
        "by_role": await tracker.by_role(),
        "by_model": await tracker.by_model(),
        "by_status": await tracker.by_status(),
    }
    return CommandResult(ok=True, text=json.dumps(data, ensure_ascii=False, indent=2), data=data)
