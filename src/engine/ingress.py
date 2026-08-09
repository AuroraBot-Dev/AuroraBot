"""AMP 持久化摄入与工具回执。

普通事件写入 inbox_events（防抖聚合）；工具回执（``tool.{status}``）不进入
Inbox，直接匹配活动完成并投递 Agent 消息（结果统一经 AMP 回 engine）。
所有摄入均经 ``submit_amp`` 直连 SQLite，无文件投递箱。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import TOOL_EVENT_TYPES

if TYPE_CHECKING:
    from src.contracts import AmpEnvelope
    from src.engine.runtime import AgentEngine


def _ingest_amp(kernel: "AgentEngine", amp: AmpEnvelope, ingested: list[str]) -> None:
    if amp.payload.type in TOOL_EVENT_TYPES:
        # 工具回执：匹配活动完成，不进入 Inbox
        kernel.consume_tool_receipt(amp)
        ingested.append(amp.header.message_id)
        return
    if kernel.store.enqueue_inbox(amp, kernel.configuration.triage):
        ingested.append(amp.header.message_id)


def persist_amp(kernel: "AgentEngine", amp: AmpEnvelope) -> bool:
    """在入口回执前将单个 AMP 幂等写入持久化 Inbox（或直接消费工具回执）。"""
    ingested: list[str] = []
    _ingest_amp(kernel, amp, ingested)
    return bool(ingested)
