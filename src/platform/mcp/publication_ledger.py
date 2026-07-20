"""Private MCP Publication dispatch and inbound loop-suppression ledger."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class PublicationRecord:
    request_id: str
    request_digest: str
    status: str
    summary: str | None
    external_message_id: str | None
    error: str | None


class MCPPublicationLedger:
    """Persist only non-secret dispatch metadata needed for recovery and loop checks."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._database = sqlite3.connect(path)
        self._database.row_factory = sqlite3.Row
        self._database.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS publications (
                request_id TEXT PRIMARY KEY,
                request_digest TEXT NOT NULL,
                endpoint_id TEXT NOT NULL,
                capability TEXT NOT NULL,
                raw_tool TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('STARTED', 'ACCEPTED', 'FAILED')),
                summary TEXT,
                external_message_id TEXT,
                error TEXT,
                delivery_observed_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS publications_external_message
                ON publications(endpoint_id, external_message_id)
                WHERE external_message_id IS NOT NULL;
            CREATE TABLE IF NOT EXISTS inbound_quarantine (
                quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint_id TEXT NOT NULL,
                external_event_id TEXT NOT NULL,
                external_message_id TEXT NOT NULL,
                origin_delivery_id TEXT,
                authored_by_self INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

    def record_started(
        self,
        request_id: str,
        request_digest: str,
        endpoint_id: str,
        capability: str,
        raw_tool: str,
    ) -> tuple[str, PublicationRecord | None]:
        existing = self.get(request_id)
        if existing is not None:
            return ("existing" if existing.request_digest == request_digest else "conflict"), existing
        self._database.execute(
            """
            INSERT INTO publications(
                request_id, request_digest, endpoint_id, capability, raw_tool, status
            ) VALUES (?, ?, ?, ?, ?, 'STARTED')
            """,
            (request_id, request_digest, endpoint_id, capability, raw_tool),
        )
        self._database.commit()
        return "started", None

    def get(self, request_id: str) -> PublicationRecord | None:
        row = self._database.execute(
            """
            SELECT request_id, request_digest, status, summary, external_message_id, error
            FROM publications WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
        if row is None:
            return None
        return PublicationRecord(
            request_id=str(row["request_id"]),
            request_digest=str(row["request_digest"]),
            status=str(row["status"]),
            summary=str(row["summary"]) if row["summary"] is not None else None,
            external_message_id=(str(row["external_message_id"]) if row["external_message_id"] is not None else None),
            error=str(row["error"]) if row["error"] is not None else None,
        )

    def record_accepted(self, request_id: str, summary: str, external_message_id: str) -> None:
        try:
            self._database.execute(
                """
                UPDATE publications
                SET status = 'ACCEPTED', summary = ?, external_message_id = ?, error = NULL
                WHERE request_id = ?
                """,
                (summary, external_message_id, request_id),
            )
            self._database.commit()
        except sqlite3.Error:
            self._database.rollback()
            raise

    def record_failed(self, request_id: str, summary: str, error: str) -> None:
        self._database.execute(
            """
            UPDATE publications
            SET status = 'FAILED', summary = ?, external_message_id = NULL, error = ?
            WHERE request_id = ?
            """,
            (summary, error, request_id),
        )
        self._database.commit()

    def observe_delivery(
        self, endpoint_id: str, external_message_id: str, origin_delivery_id: str | None
    ) -> str | None:
        row = self._database.execute(
            """
            SELECT request_id FROM publications
            WHERE endpoint_id = ? AND external_message_id = ? AND status = 'ACCEPTED'
            """,
            (endpoint_id, external_message_id),
        ).fetchone()
        if row is None:
            return None
        request_id = str(row["request_id"])
        if origin_delivery_id is not None and origin_delivery_id != request_id:
            return ""
        self._database.execute(
            "UPDATE publications SET delivery_observed_at = ? WHERE request_id = ?",
            (datetime.now(UTC).isoformat(), request_id),
        )
        self._database.commit()
        return request_id

    def quarantine(
        self,
        *,
        endpoint_id: str,
        external_event_id: str,
        external_message_id: str,
        origin_delivery_id: str | None,
        authored_by_self: bool,
        reason: str,
    ) -> None:
        self._database.execute(
            """
            INSERT INTO inbound_quarantine(
                endpoint_id, external_event_id, external_message_id, origin_delivery_id,
                authored_by_self, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                endpoint_id,
                external_event_id,
                external_message_id,
                origin_delivery_id,
                int(authored_by_self),
                reason,
                datetime.now(UTC).isoformat(),
            ),
        )
        self._database.commit()

    def close(self) -> None:
        self._database.close()
