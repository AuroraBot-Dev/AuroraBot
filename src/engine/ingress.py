"""AMP 持久化摄入、工具回执与幂等分发（RFC 0208/0210/0211 拆包）。

普通事件写入 inbox_events（防抖聚合）；工具回执（``tool.{status}``）不进入
Inbox，直接匹配活动完成并投递 Agent 消息（RFC 0211：结果统一经 AMP 回 engine）。
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from src.contracts import AmpEnvelope, AmpValidationError
from src.utils import get_logger, read_json

if TYPE_CHECKING:
    from pathlib import Path

    from src.engine.runtime import AgentEngine

logger = get_logger("aurora.engine.ingress")

TOOL_EVENT_TYPES = frozenset({"tool.succeeded", "tool.failed", "tool.unknown"})


def ingest_ready(kernel: "AgentEngine") -> tuple[str, ...]:
    """摄入 Inbox 文件：普通事件入 Inbox，工具回执直接消费。"""
    ingested: list[str] = []
    for p in sorted(kernel._inbox.glob("*.json")):
        try:
            amp = AmpEnvelope.parse(read_json(p))
        except (OSError, ValueError, TypeError, AmpValidationError) as error:
            logger.warning("AMP ingress rejected file=%s reason=%s", p.name, error)
            _archive_inbox(kernel, p, "rejected")
            continue
        try:
            _ingest_amp_file(kernel, amp, p, ingested)
        except (ValueError, TypeError) as error:
            logger.warning("AMP ingress rejected file=%s reason=%s", p.name, error)
            _archive_inbox(kernel, p, "rejected")
    return tuple(ingested)


def _ingest_amp(kernel: "AgentEngine", amp: AmpEnvelope, ingested: list[str]) -> None:
    if amp.payload.type in TOOL_EVENT_TYPES:
        # 工具回执：匹配活动完成，不进入 Inbox（RFC 0211）
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


def _ingest_amp_file(kernel: "AgentEngine", amp: AmpEnvelope, path: "Path", ingested: list[str]) -> None:
    before = len(ingested)
    _ingest_amp(kernel, amp, ingested)
    if len(ingested) > before:
        _archive_inbox(kernel, path, "accepted")
    else:
        _archive_inbox(kernel, path, "duplicate")


def _archive_inbox(kernel: "AgentEngine", source: "Path", category: str) -> None:
    destination_dir = kernel._archive / "inbox" / category
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    if destination.exists():
        destination = destination_dir / f"{source.stem}-{os.urandom(4).hex()}{source.suffix}"
    source.replace(destination)
