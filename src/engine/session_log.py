"""engine 会话的追加式 JSONL 日志。

每个会话一个追加式文件：``data/engine/sessions/<session_id>.jsonl``，每行一条 JSON 记录，
按时间顺序串起该会话的入站 AMP、Task 准入与终态，作为可读审计与复盘依据。

运行态权威仍是 SQLite WAL（RFC 0201）；本日志只追加、不回写，不参与热路径决策。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.agent import TaskState
    from src.contracts.amp import AmpEnvelope

logger = get_logger("aurora.engine.session-log")

_SESSION_FILE_SAFE = re.compile(r"[^A-Za-z0-9._-]")
_MAX_FILE_STEM = 200


def session_file_stem(session_id: str) -> str:
    """将会话 ID 规整为安全的文件主干名，过长时截断并附加短摘要。"""
    safe = _SESSION_FILE_SAFE.sub("_", session_id).strip(".")
    if not safe:
        safe = "unknown"
    if len(safe) <= _MAX_FILE_STEM:
        return safe
    digest = hashlib.sha256(safe.encode("utf-8")).hexdigest()[:8]
    return f"{safe[:_MAX_FILE_STEM]}-{digest}"


class SessionLog:
    """以会话为粒度的追加式 JSONL 写入器。

    每条记录均为单行 JSON：``{"ts": ISO-8601 UTC, "kind": "...", ...}``。
    写入失败只记 warning，不打断 engine 热路径。
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def append(self, session_id: str, kind: str, **fields: Any) -> None:
        record: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "kind": kind,
            "session_id": session_id,
        }
        record.update(fields)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        path = self._directory / f"{session_file_stem(session_id)}.jsonl"
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            logger.warning(
                "Session log append failed path=%s kind=%s error_type=%s",
                path.name,
                kind,
                os.error.__name__,
            )

    def amp_in(self, amp: "AmpEnvelope") -> None:
        self.append(
            amp.payload.session_id,
            "amp.in",
            message_id=amp.header.message_id,
            event_type=amp.payload.type,
            summary=amp.payload.summary,
            source_app=amp.header.source["app"],
            source_instance=amp.header.source["instance"],
        )

    def task_admitted(self, task_id: str, session_id: str, root_summary: str) -> None:
        self.append(session_id, "task.admitted", task_id=task_id, root_summary=root_summary)

    def task_finished(self, task: "TaskState") -> None:
        self.append(
            task.session_id,
            "task.finished",
            task_id=task.task_id,
            status=str(task.status),
            root_summary=task.root_summary,
        )
