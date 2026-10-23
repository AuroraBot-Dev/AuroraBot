"""复用的离线场景构造与替身，不依赖测试用例模块。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aurora_bot.contracts import WorldCommit, WorldFrontier

_NOW = datetime(2026, 10, 18, tzinfo=UTC)


def _fact(identity: str, text: str, cursor: int, **links: list[str]) -> WorldCommit:
    """创建早于当前窗口的经历及其显式关系。"""
    return WorldCommit(
        identity,
        "environment.fact",
        "test",
        text,
        _NOW - timedelta(days=1),
        {"test:world/facts": cursor},
        WorldFrontier(),
        {"memory": links},
        cursor,
        _NOW - timedelta(hours=2),
    )
