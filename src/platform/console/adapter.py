"""Console Publication executor with a durable idempotency and recovery ledger."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from src.contracts.agent import CapabilityDescriptor
from src.localhost.ports import PublicationExecutionRequest, PublicationOutcome

if TYPE_CHECKING:
    from pathlib import Path

CONSOLE_ENDPOINT = "console.local"
CONSOLE_AUDIENCE = "owner.local"
CONSOLE_SEND_CAPABILITY = "org.aurora.console.send_message"
CONSOLE_SEND_DESCRIPTOR = CapabilityDescriptor(
    id=CONSOLE_SEND_CAPABILITY,
    description="Reply to the owner through the local Console.",
    parameters_schema={
        "type": "object",
        "properties": {"text": {"type": "string", "minLength": 1}},
        "required": ["text"],
        "additionalProperties": False,
    },
    kind="publication",
    endpoint=CONSOLE_ENDPOINT,
    operation="reply",
    root_only=True,
)


class ConsolePlatform:
    """Own Console routes, output, and durable Publication dispatch state."""

    def __init__(self, ledger_path: Path | None = None, *, reply_route_ttl_seconds: float = 3600.0) -> None:
        if reply_route_ttl_seconds <= 0:
            raise ValueError("reply_route_ttl_seconds must be positive")
        self._reply_route_ttl_seconds = reply_route_ttl_seconds
        if ledger_path is not None:
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._database = sqlite3.connect(str(ledger_path) if ledger_path is not None else ":memory:")
        self._database.row_factory = sqlite3.Row
        self._database.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS reply_routes (
                route_ref TEXT PRIMARY KEY,
                external_event_id TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS publications (
                request_id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('dispatch_started', 'accepted', 'failed')),
                summary TEXT,
                external_message_id TEXT,
                error TEXT
            );
            """
        )
        columns = {str(row["name"]) for row in self._database.execute("PRAGMA table_info(reply_routes)")}
        if "expires_at" not in columns:
            self._database.execute("ALTER TABLE reply_routes ADD COLUMN expires_at TEXT")
            self._database.execute(
                "UPDATE reply_routes SET expires_at = ? WHERE expires_at IS NULL",
                (datetime.now(UTC).isoformat(),),
            )
            self._database.commit()
        publication_columns = {str(row["name"]) for row in self._database.execute("PRAGMA table_info(publications)")}
        if "request_digest" not in publication_columns:
            self._database.execute("ALTER TABLE publications ADD COLUMN request_digest TEXT")
            self._database.commit()
        self._messages: list[str] = []
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    def register_reply_route(self, route_ref: str, external_event_id: str) -> None:
        """Persist the fixed Console route before its ingress AMP is submitted."""
        now = datetime.now(UTC)
        self._cleanup_reply_routes(now)
        self._database.execute(
            "INSERT OR IGNORE INTO reply_routes(route_ref, external_event_id, expires_at) VALUES (?, ?, ?)",
            (route_ref, external_event_id, (now + timedelta(seconds=self._reply_route_ttl_seconds)).isoformat()),
        )
        self._database.commit()

    async def execute_publication(self, request: PublicationExecutionRequest) -> PublicationOutcome:
        previous = self._publication_outcome(request)
        if previous is not None:
            return previous
        error = self._validate(request)
        if error is not None:
            return self._record_failure(request, error)
        self._database.execute(
            "INSERT INTO publications(request_id, text, request_digest, status) VALUES (?, ?, ?, 'dispatch_started')",
            (request.request_id, request.text, _request_digest(request)),
        )
        self._database.commit()

        self._messages.append(request.text)
        self._queue.put_nowait(request.text)
        external_message_id = str(uuid5(NAMESPACE_URL, f"aurora-console-publication:{request.request_id}"))
        summary = "Console reply accepted"
        self._database.execute(
            "UPDATE publications SET status = 'accepted', summary = ?, external_message_id = ? WHERE request_id = ?",
            (summary, external_message_id, request.request_id),
        )
        self._database.commit()
        return PublicationOutcome("accepted", summary, external_message_id=external_message_id)

    async def recover_publication(self, request: PublicationExecutionRequest) -> PublicationOutcome:
        outcome = self._publication_outcome(request)
        if outcome is not None:
            return outcome
        return PublicationOutcome(
            "failed",
            "Console reply was interrupted before dispatch",
            error="interrupted_before_dispatch",
        )

    def _publication_outcome(self, request: PublicationExecutionRequest) -> PublicationOutcome | None:
        row = self._database.execute(
            "SELECT * FROM publications WHERE request_id = ?", (request.request_id,)
        ).fetchone()
        if row is None:
            return None
        stored_digest = row["request_digest"]
        if stored_digest is None:
            return PublicationOutcome(
                "delivery_unknown",
                "Console reply predates request identity tracking",
                error="legacy_publication_request_identity_unknown",
            )
        if stored_digest != _request_digest(request):
            return PublicationOutcome(
                "failed",
                "Console Publication idempotency conflict",
                error="idempotency conflict: request ID was reused with a different request",
            )
        status = str(row["status"])
        if status == "dispatch_started":
            return PublicationOutcome(
                "delivery_unknown",
                "Console reply delivery is unknown",
                error="dispatch_started_without_terminal_outcome",
            )
        if status == "accepted":
            return PublicationOutcome(
                "accepted",
                str(row["summary"]),
                external_message_id=str(row["external_message_id"]),
            )
        return PublicationOutcome("failed", str(row["summary"]), error=str(row["error"]))

    def _validate(self, request: PublicationExecutionRequest) -> str | None:
        if request.capability != CONSOLE_SEND_CAPABILITY:
            return f"unsupported Console capability: {request.capability}"
        if request.endpoint_id != CONSOLE_ENDPOINT or request.operation != "reply":
            return "Console only accepts reply Publications for console.local"
        if not request.text:
            return "Console Publication text must be non-empty"
        if request.target_audience_ref != CONSOLE_AUDIENCE or request.route_ref is None:
            return "Console Publication route is invalid"
        now = datetime.now(UTC)
        self._cleanup_reply_routes(now)
        route = self._database.execute(
            "SELECT 1 FROM reply_routes WHERE route_ref = ? AND expires_at > ?",
            (request.route_ref, now.isoformat()),
        ).fetchone()
        return None if route is not None else "Console reply route is unknown"

    def _cleanup_reply_routes(self, now: datetime) -> None:
        self._database.execute("DELETE FROM reply_routes WHERE expires_at <= ?", (now.isoformat(),))
        self._database.commit()

    def _record_failure(self, request: PublicationExecutionRequest, error: str) -> PublicationOutcome:
        summary = "Console reply failed"
        self._database.execute(
            "INSERT INTO publications(request_id, text, request_digest, status, summary, error) "
            "VALUES (?, ?, ?, 'failed', ?, ?)",
            (request.request_id, request.text, _request_digest(request), summary, error),
        )
        self._database.commit()
        return PublicationOutcome("failed", summary, error=error)

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


def _request_digest(request: PublicationExecutionRequest) -> str:
    canonical = json.dumps(asdict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
