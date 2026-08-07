"""AMP 持久化摄入与幂等回执（RFC 0208 拆包）。

从 runtime.py 拆出的纯函数集合：把 Inbox 文件与内存队列写入持久化
inbox_events，并归档已接受/拒绝/重复的输入文件。不持有运行时状态。
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import TYPE_CHECKING

from src.contracts import AmpEnvelope, AmpValidationError
from src.utils import get_logger, read_json

if TYPE_CHECKING:
    from pathlib import Path

    from src.engine.runtime import EngineState

logger = get_logger("aurora.engine.ingress")


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    RESERVED_TOOL_EVENT = "Tool receipt event types are reserved for internal Runtime use"


def ingest_ready(kernel: "EngineState") -> tuple[str, ...]:
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


def _ingest_amp(kernel: "EngineState", amp: AmpEnvelope, ingested: list[str]) -> None:
    if amp.payload.type in {"tool.succeeded", "tool.failed", "tool.unknown"}:
        raise ValueError(_Msg.RESERVED_TOOL_EVENT)
    if kernel.store.enqueue_inbox(amp, kernel.configuration.triage):
        kernel._session_log.amp_in(amp)
        ingested.append(amp.header.message_id)


def persist_amp(kernel: "EngineState", amp: AmpEnvelope) -> bool:
    """在入口回执前将单个 AMP 幂等写入持久化 Inbox。"""
    ingested: list[str] = []
    _ingest_amp(kernel, amp, ingested)
    return bool(ingested)


def _ingest_amp_file(kernel: "EngineState", amp: AmpEnvelope, path: "Path", ingested: list[str]) -> None:
    before = len(ingested)
    _ingest_amp(kernel, amp, ingested)
    if len(ingested) > before:
        _archive_inbox(kernel, path, "accepted")
    else:
        _archive_inbox(kernel, path, "duplicate")


def _archive_inbox(kernel: "EngineState", source: "Path", category: str) -> None:
    destination_dir = kernel._archive / "inbox" / category
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    if destination.exists():
        destination = destination_dir / f"{source.stem}-{os.urandom(4).hex()}{source.suffix}"
    source.replace(destination)
