"""Console Tool executor with a durable idempotency and recovery ledger."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import asdict
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from src.contracts.agent import CapabilityDescriptor
from src.localhost.ports import ToolExecutionRequest, ToolOutcome

if TYPE_CHECKING:
    from pathlib import Path

CONSOLE_SEND_CAPABILITY = "org.aurora.console.send"
CONSOLE_SEND_DESCRIPTOR = CapabilityDescriptor(
    id=CONSOLE_SEND_CAPABILITY,
    description="Send text through the local Console.",
    parameters_schema={
        "type": "object",
        "properties": {"text": {"type": "string", "minLength": 1}},
        "required": ["text"],
        "additionalProperties": False,
    },
)


class ConsolePlatform:
    """Own Console output and durable Tool dispatch state."""

    def __init__(self, ledger_path: Path | None = None) -> None:
        if ledger_path is not None:
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._database = sqlite3.connect(str(ledger_path) if ledger_path is not None else ":memory:")
        self._database.row_factory = sqlite3.Row
        self._database.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS tool_requests (
                request_id TEXT PRIMARY KEY,
                request_digest TEXT NOT NULL,
                text TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('dispatch_started', 'succeeded', 'failed')),
                summary TEXT,
                external_message_id TEXT,
                error TEXT
            );
            """
        )
        self._messages: list[str] = []
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    async def execute_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        previous = self._tool_outcome(request)
        if previous is not None:
            return previous
        error = self._validate(request)
        if error is not None:
            return self._record_failure(request, error)
        text = str(request.parameters["text"])
        self._database.execute(
            "INSERT INTO tool_requests(request_id, request_digest, text, status) VALUES (?, ?, ?, 'dispatch_started')",
            (request.request_id, _request_digest(request), text),
        )
        self._database.commit()

        self._messages.append(text)
        self._queue.put_nowait(text)
        external_message_id = str(uuid5(NAMESPACE_URL, f"aurora-console-tool:{request.request_id}"))
        summary = "Console message sent"
        self._database.execute(
            "UPDATE tool_requests SET status = 'succeeded', summary = ?, external_message_id = ? WHERE request_id = ?",
            (summary, external_message_id, request.request_id),
        )
        self._database.commit()
        return ToolOutcome("succeeded", summary, result={"message_id": external_message_id})

    async def recover_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        outcome = self._tool_outcome(request)
        if outcome is not None:
            return outcome
        return ToolOutcome(
            "failed",
            "Console send was interrupted before dispatch",
            error="interrupted_before_dispatch",
        )

    def _tool_outcome(self, request: ToolExecutionRequest) -> ToolOutcome | None:
        row = self._database.execute(
            "SELECT * FROM tool_requests WHERE request_id = ?", (request.request_id,)
        ).fetchone()
        if row is None:
            return None
        if str(row["request_digest"]) != _request_digest(request):
            return ToolOutcome(
                "failed",
                "Console Tool idempotency conflict",
                error="idempotency conflict: request ID was reused with a different request",
            )
        status = str(row["status"])
        if status == "dispatch_started":
            return ToolOutcome(
                "unknown",
                "Console message delivery is unknown",
                error="dispatch_started_without_terminal_outcome",
            )
        if status == "succeeded":
            return ToolOutcome(
                "succeeded",
                str(row["summary"]),
                result={"message_id": str(row["external_message_id"])},
            )
        return ToolOutcome("failed", str(row["summary"]), error=str(row["error"]))

    @staticmethod
    def _validate(request: ToolExecutionRequest) -> str | None:
        if request.capability != CONSOLE_SEND_CAPABILITY:
            return f"unsupported Console capability: {request.capability}"
        if set(request.parameters) != {"text"}:
            return "Console send parameters must contain only text"
        text = request.parameters.get("text")
        if not isinstance(text, str) or not text.strip():
            return "Console send text must be a non-empty string"
        return None

    def _record_failure(self, request: ToolExecutionRequest, error: str) -> ToolOutcome:
        summary = "Console send failed"
        text = request.parameters.get("text")
        self._database.execute(
            "INSERT INTO tool_requests(request_id, request_digest, text, status, summary, error) "
            "VALUES (?, ?, ?, 'failed', ?, ?)",
            (request.request_id, _request_digest(request), text if isinstance(text, str) else "", summary, error),
        )
        self._database.commit()
        return ToolOutcome("failed", summary, error=error)

    async def next_message(self) -> str:
        message = await self._queue.get()
        self._messages.remove(message)
        return message

    def drain_messages(self) -> tuple[str, ...]:
        messages = tuple(self._messages)
        self._messages.clear()
        while not self._queue.empty():
            self._queue.get_nowait()
        return messages

    def close(self) -> None:
        self._database.close()


def _request_digest(request: ToolExecutionRequest) -> str:
    canonical = json.dumps(asdict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
