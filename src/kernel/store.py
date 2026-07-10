# ruff: noqa: E501, TC003
"""SQLite metadata and immutable object storage for cognitive events."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from src.kernel.models import CognitiveEvent, EventState, utcnow


class EventStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.objects = root / ".aurora" / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            root / ".aurora" / "events.sqlite", isolation_level=None, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, object_id TEXT NOT NULL,
                source TEXT NOT NULL, session_id TEXT NOT NULL, episode_id TEXT NOT NULL,
                causation_id TEXT, tags TEXT NOT NULL, state TEXT NOT NULL, owner_id TEXT,
                available_at TEXT, created_at TEXT NOT NULL, hop INTEGER NOT NULL,
                max_hops INTEGER NOT NULL, version INTEGER NOT NULL DEFAULT 0, error TEXT
            )
            """
        )
        self._connection.execute("CREATE INDEX IF NOT EXISTS idx_events_ready ON events(state, available_at)")
        self._connection.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, created_at)")

    def close(self) -> None:
        self._connection.close()

    def create(self, event: CognitiveEvent) -> None:
        object_id = self.put_object(json.dumps(event.payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        self._connection.execute(
            """
            INSERT INTO events(event_id,event_type,object_id,source,session_id,episode_id,causation_id,tags,state,
              owner_id,available_at,created_at,hop,max_hops,version,error)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
            """,
            (
                event.event_id,
                event.event_type,
                object_id,
                event.source,
                event.session_id,
                event.episode_id,
                event.causation_id,
                json.dumps(event.tags, ensure_ascii=False, sort_keys=True),
                EventState.PENDING.value,
                None,
                self._time_text(event.available_at),
                self._time_text(event.created_at),
                event.hop,
                event.max_hops,
                0,
            ),
        )

    def put_object(self, content: bytes) -> str:
        object_id = hashlib.sha256(content).hexdigest()
        path = self.objects / object_id
        if not path.exists():
            path.write_bytes(content)
        return object_id

    def list_ready(self, now: datetime | None = None) -> list[CognitiveEvent]:
        moment = self._time_text(now or utcnow())
        rows = self._connection.execute(
            "SELECT * FROM events WHERE state = ? AND owner_id IS NULL AND (available_at IS NULL OR available_at <= ?) ORDER BY created_at",
            (EventState.PENDING.value, moment),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def claim(self, event_id: str, node_id: str) -> bool:
        cursor = self._connection.execute(
            "UPDATE events SET state=?, owner_id=?, version=version+1 WHERE event_id=? AND state=? AND owner_id IS NULL",
            (EventState.PROCESSING.value, node_id, event_id, EventState.PENDING.value),
        )
        return cursor.rowcount == 1

    def archive(self, event_id: str, node_id: str) -> None:
        self._connection.execute(
            "UPDATE events SET state=?, owner_id=NULL, version=version+1 WHERE event_id=? AND owner_id=?",
            (EventState.ARCHIVED.value, event_id, node_id),
        )

    def archive_terminal(self, event_id: str) -> None:
        self._connection.execute(
            "UPDATE events SET state=?, owner_id=NULL, version=version+1 WHERE event_id=? AND state=?",
            (EventState.ARCHIVED.value, event_id, EventState.PENDING.value),
        )

    def release(self, event_id: str, node_id: str) -> None:
        self._connection.execute(
            "UPDATE events SET state=?, owner_id=NULL, version=version+1 WHERE event_id=? AND owner_id=?",
            (EventState.PENDING.value, event_id, node_id),
        )

    def fail(self, event_id: str, node_id: str, error: str) -> None:
        self._connection.execute(
            "UPDATE events SET state=?, owner_id=NULL, error=?, version=version+1 WHERE event_id=? AND owner_id=?",
            (EventState.ERROR.value, error, event_id, node_id),
        )

    def list_events(self, *, event_type: str | None = None, session_id: str | None = None) -> list[CognitiveEvent]:
        clauses: list[str] = []
        params: list[str] = []
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connection.execute(f"SELECT * FROM events{where} ORDER BY created_at", params).fetchall()
        return [self._from_row(row) for row in rows]

    def latest_context(self, session_id: str) -> CognitiveEvent | None:
        row = self._connection.execute(
            "SELECT * FROM events WHERE event_type='context.frame' AND session_id=? ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def event_state_counts(self) -> dict[str, int]:
        rows = self._connection.execute("SELECT state, COUNT(*) AS count FROM events GROUP BY state").fetchall()
        return {str(row["state"]): int(row["count"]) for row in rows}

    def _from_row(self, row: sqlite3.Row) -> CognitiveEvent:
        payload = json.loads((self.objects / row["object_id"]).read_bytes().decode("utf-8"))
        return CognitiveEvent(
            event_id=row["event_id"],
            event_type=row["event_type"],
            payload=payload,
            source=row["source"],
            session_id=row["session_id"],
            episode_id=row["episode_id"],
            causation_id=row["causation_id"],
            tags=json.loads(row["tags"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            available_at=datetime.fromisoformat(row["available_at"]) if row["available_at"] else None,
            hop=int(row["hop"]),
            max_hops=int(row["max_hops"]),
        )

    @staticmethod
    def _time_text(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None
