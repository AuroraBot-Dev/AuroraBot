"""SQLite persistence owned by the Dashboard Platform."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.platform.dashboard.security import new_token

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    avatar_url TEXT,
    is_bot INTEGER NOT NULL DEFAULT 0 CHECK (is_bot IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(owner_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_message_id TEXT NOT NULL,
    sender_id INTEGER NOT NULL,
    receiver_id INTEGER NOT NULL,
    message_type TEXT NOT NULL,
    content TEXT,
    attachment_id INTEGER,
    status TEXT NOT NULL,
    amp_message_id TEXT UNIQUE,
    source_effect_request_id TEXT UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(sender_id) REFERENCES users(id),
    FOREIGN KEY(receiver_id) REFERENCES users(id),
    FOREIGN KEY(attachment_id) REFERENCES attachments(id),
    UNIQUE(sender_id, client_message_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_sender_receiver_id
    ON messages(sender_id, receiver_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_receiver_sender_id
    ON messages(receiver_id, sender_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_sync
    ON messages(id, sender_id, receiver_id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ChatStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(_SCHEMA)
        token_path = self.database_path.parent / "Token.txt"
        token_path.write_text(new_token())

    def fetch_one(self, query: str, parameters: Iterable[object] = ()) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(query, tuple(parameters)).fetchone()

    def fetch_all(self, query: str, parameters: Iterable[object] = ()) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(query, tuple(parameters)).fetchall()

    def execute(self, query: str, parameters: Iterable[object] = ()) -> int:
        with self.connect() as connection:
            cursor = connection.execute(query, tuple(parameters))
            connection.commit()
            assert cursor.lastrowid is not None
            return int(cursor.lastrowid)

    def ensure_bot(self, username: str, display_name: str, avatar_url: str | None) -> sqlite3.Row:
        now = _now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO users(username, password_hash, display_name, avatar_url, is_bot, created_at, updated_at)
                VALUES (?, 'disabled', ?, ?, 1, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    display_name = excluded.display_name,
                    avatar_url = excluded.avatar_url,
                    is_bot = 1,
                    updated_at = excluded.updated_at
                """,
                (username, display_name, avatar_url, now, now),
            )
            row = connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            assert row is not None
            return row

    def create_user(self, username: str, password_hash: str) -> sqlite3.Row:
        now = _now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users(username, password_hash, display_name, is_bot, created_at, updated_at)
                VALUES (?, ?, ?, 0, ?, ?)
                """,
                (username, password_hash, username, now, now),
            )
            row = connection.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
            assert row is not None
            return row

    def create_message(
        self,
        *,
        client_message_id: str,
        sender_id: int,
        receiver_id: int,
        message_type: str,
        content: str | None,
        attachment_id: int | None,
        status: str = "saved",
        amp_message_id: str | None = None,
        source_effect_request_id: str | None = None,
    ) -> tuple[sqlite3.Row, bool]:
        now = _now()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO messages(
                        client_message_id, sender_id, receiver_id, message_type, content, attachment_id,
                        status, amp_message_id, source_effect_request_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        client_message_id,
                        sender_id,
                        receiver_id,
                        message_type,
                        content,
                        attachment_id,
                        status,
                        amp_message_id,
                        source_effect_request_id,
                        now,
                    ),
                )
                row = connection.execute("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)).fetchone()
                connection.commit()
                assert row is not None
                return row, True
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM messages WHERE sender_id = ? AND client_message_id = ?",
                    (sender_id, client_message_id),
                ).fetchone()
                if row is None and source_effect_request_id is not None:
                    row = connection.execute(
                        "SELECT * FROM messages WHERE source_effect_request_id = ?",
                        (source_effect_request_id,),
                    ).fetchone()
                if row is None:
                    raise
                return row, False

    def message_with_attachment(self, message_id: int) -> sqlite3.Row | None:
        return self.fetch_one(
            """
            SELECT m.*, a.original_name, a.stored_name, a.mime_type, a.size
            FROM messages m LEFT JOIN attachments a ON a.id = m.attachment_id
            WHERE m.id = ?
            """,
            (message_id,),
        )

    def messages_with_attachments(self, query: str, parameters: Iterable[object]) -> list[sqlite3.Row]:
        return self.fetch_all(query, parameters)
