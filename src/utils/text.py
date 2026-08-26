"""模型上下文的文本装配与有界摘要助手（无上层依赖）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def bounded_summary(summaries: Sequence[str], *, limit: int = 600) -> str:
    """从事件摘要列表拼接有界摘要；空输入回退到占位文本。"""
    summary = "；".join(summaries)
    if len(summary) > limit:
        summary = summary[: limit - 1] + "…"
    return summary or "暂无摘要"
