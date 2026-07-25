"""Dashboard 平台自有的 SQLite 持久化层。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel

from src.platform.dashboard.security import new_token

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


_MIGRATION_1 = """
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
    source_publication_request_id TEXT UNIQUE,
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

_MIGRATION_2 = """
ALTER TABLE messages RENAME TO messages_legacy;
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_message_id TEXT NOT NULL,
    sender_id INTEGER NOT NULL,
    receiver_id INTEGER NOT NULL,
    message_type TEXT NOT NULL,
    content TEXT,
    attachment_id INTEGER,
    status TEXT NOT NULL,
    amp_message_id TEXT UNIQUE,
    source_publication_request_id TEXT UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(sender_id) REFERENCES users(id),
    FOREIGN KEY(receiver_id) REFERENCES users(id),
    FOREIGN KEY(attachment_id) REFERENCES attachments(id),
    UNIQUE(sender_id, client_message_id)
);
INSERT INTO messages(
    id, client_message_id, sender_id, receiver_id, message_type, content,
    attachment_id, status, amp_message_id, created_at
)
SELECT
    id, client_message_id, sender_id, receiver_id, message_type, content,
    attachment_id, status, amp_message_id, created_at
FROM messages_legacy;
DROP TABLE messages_legacy;
CREATE INDEX idx_messages_sender_receiver_id
    ON messages(sender_id, receiver_id, id);
CREATE INDEX idx_messages_receiver_sender_id
    ON messages(receiver_id, sender_id, id);
CREATE INDEX idx_messages_sync
    ON messages(id, sender_id, receiver_id);
CREATE TABLE dashboard_reply_routes (
    route_ref TEXT PRIMARY KEY,
    external_event_id TEXT NOT NULL UNIQUE,
    external_message_id TEXT NOT NULL UNIQUE,
    owner_user_id INTEGER NOT NULL,
    conversation_ref TEXT NOT NULL,
    actor_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(owner_user_id) REFERENCES users(id)
);
CREATE TABLE dashboard_publications (
    request_id TEXT PRIMARY KEY,
    route_ref TEXT,
    capability TEXT NOT NULL,
    endpoint_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('dispatch_started', 'accepted', 'failed')),
    summary TEXT,
    external_message_id TEXT UNIQUE,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_MIGRATION_3 = """
ALTER TABLE dashboard_reply_routes ADD COLUMN expires_at TEXT;
UPDATE dashboard_reply_routes
SET expires_at = strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
WHERE expires_at IS NULL;
"""

_MIGRATION_4 = """
ALTER TABLE users ADD COLUMN is_owner INTEGER NOT NULL DEFAULT 0 CHECK (is_owner IN (0, 1));
CREATE UNIQUE INDEX idx_users_single_owner ON users(is_owner) WHERE is_owner = 1;
"""

_MIGRATION_5 = """
ALTER TABLE messages RENAME COLUMN source_publication_request_id TO source_tool_request_id;
DROP TABLE dashboard_reply_routes;
ALTER TABLE dashboard_publications RENAME TO dashboard_publications_legacy;
CREATE TABLE dashboard_tool_requests (
    request_id TEXT PRIMARY KEY,
    request_digest TEXT,
    text TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('dispatch_started', 'succeeded', 'failed')),
    summary TEXT,
    external_message_id TEXT UNIQUE,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
INSERT INTO dashboard_tool_requests(
    request_id, text, status, summary, external_message_id, error, created_at, updated_at
)
SELECT request_id, text, CASE status WHEN 'accepted' THEN 'succeeded' ELSE status END,
       summary, external_message_id, error, created_at, updated_at
FROM dashboard_publications_legacy;
DROP TABLE dashboard_publications_legacy;
"""

_MIGRATIONS = (_MIGRATION_1, _MIGRATION_2, _MIGRATION_3, _MIGRATION_4, _MIGRATION_5)

console = Console(highlight=False)


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    SCHEMA_VERSION_AHEAD = "Dashboard 数据库 schema {version} 比当前运行时版本更新"
    TOKEN_EMPTY = "Dashboard 启动 token 为空"
    OWNER_ALREADY_BOUND = "Dashboard 所有者已绑定到 {username}"


def _now() -> str:
    """获取当前 UTC 时间的 ISO 格式字符串。"""
    return datetime.now(UTC).isoformat()


def _print_token(token: str) -> None:
    """在终端中以 Rich Panel 格式打印启动 Token 和保管提示。"""
    content = (
        f"[bold yellow]Token:[/bold yellow] [bold green]{token}[/bold green]\n\n"
        "[dim]请妥善保管 Token。\n"
        "你也可以在 [bold]data/dashboard/Token.txt[/bold] 查看你的 Token。\n"
        "如果不慎泄露，请删除 Token.txt 以重新生成。[/dim]"
    )
    console.print(Panel(content, title="Dashboard Auth"))


class ChatStore:
    """Dashboard 聊天数据的 SQLite 持久化存储。

    管理用户、会话、消息、附件和 Tool 请求的 CRUD 操作，
    以及数据库迁移和启动 Token 管理。
    """

    def __init__(self, database_path: Path) -> None:
        """绑定数据库文件路径。

        Args:
            database_path: SQLite 数据库文件路径。
        """
        self.database_path = database_path

    def connect(self) -> sqlite3.Connection:
        """创建并返回配置好的 SQLite 连接（WAL + 外键 + busy timeout）。"""
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self) -> None:
        """初始化数据库：创建目录、执行迁移、生成启动 Token。

        使用 ``user_version`` 实现增量迁移；若首次启动且 Token.txt 不存在，
        则自动生成并打印启动 Token。
        """
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > len(_MIGRATIONS):
                raise RuntimeError(_Msg.SCHEMA_VERSION_AHEAD.format(version=version))
            for target_version, migration in enumerate(_MIGRATIONS[version:], start=version + 1):
                connection.executescript(
                    f"BEGIN IMMEDIATE;\n{migration}\nPRAGMA user_version = {target_version};\nCOMMIT;"
                )
        token_path = self.database_path.parent / "Token.txt"
        try:
            with token_path.open("x", encoding="utf-8") as token_file:
                t = new_token()
                token_file.write(t)
                _print_token(t)
        except FileExistsError:
            pass

    def bootstrap_token(self) -> str:
        """读取并返回启动 Token。"""
        token = (self.database_path.parent / "Token.txt").read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError(_Msg.TOKEN_EMPTY)
        return token

    def ensure_owner(self, username: str) -> sqlite3.Row:
        """确保 Dashboard 所有者用户存在且绑定到指定用户名。

        若已有所有者但用户名不匹配则抛出异常。
        """
        now = _now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            owner = connection.execute("SELECT * FROM users WHERE is_owner = 1").fetchone()
            if owner is not None:
                if str(owner["username"]) != username:
                    raise RuntimeError(_Msg.OWNER_ALREADY_BOUND.format(username=owner["username"]))
                connection.commit()
                return owner
            connection.execute(
                """
                INSERT INTO users(username, password_hash, display_name, is_bot, is_owner, created_at, updated_at)
                VALUES (?, 'disabled', ?, 0, 1, ?, ?)
                ON CONFLICT(username) DO UPDATE SET is_owner = 1, is_bot = 0, updated_at = excluded.updated_at
                """,
                (username, username, now, now),
            )
            owner = connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            connection.commit()
            assert owner is not None
            return owner

    def fetch_one(self, query: str, parameters: Iterable[object] = ()) -> sqlite3.Row | None:
        """执行查询并返回单行结果（无结果时返回 None）。"""
        with self.connect() as connection:
            return connection.execute(query, tuple(parameters)).fetchone()

    def fetch_all(self, query: str, parameters: Iterable[object] = ()) -> list[sqlite3.Row]:
        """执行查询并返回所有行。"""
        with self.connect() as connection:
            return connection.execute(query, tuple(parameters)).fetchall()

    def execute(self, query: str, parameters: Iterable[object] = ()) -> int:
        """执行写入操作并返回 ``lastrowid``。"""
        with self.connect() as connection:
            cursor = connection.execute(query, tuple(parameters))
            connection.commit()
            assert cursor.lastrowid is not None
            return int(cursor.lastrowid)

    def ensure_bot(self, username: str, display_name: str, avatar_url: str | None) -> sqlite3.Row:
        """确保 Bot 用户存在，使用 upsert 语义更新显示名和头像。"""
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
        source_tool_request_id: str | None = None,
    ) -> tuple[sqlite3.Row, bool]:
        """创建消息记录，支持幂等插入（通过唯一约束检测重复）。

        Returns:
            ``(消息行, 是否新建)`` 的元组。
        """
        now = _now()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO messages(
                        client_message_id, sender_id, receiver_id, message_type, content, attachment_id,
                        status, amp_message_id, source_tool_request_id, created_at
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
                        source_tool_request_id,
                        now,
                    ),
                )
                row = connection.execute("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)).fetchone()
                connection.commit()
                assert row is not None
                return row, True
            except sqlite3.IntegrityError:
                # 唯一约束冲突 → 取出已存在的行（幂等）
                row = connection.execute(
                    "SELECT * FROM messages WHERE sender_id = ? AND client_message_id = ?",
                    (sender_id, client_message_id),
                ).fetchone()
                if row is None and source_tool_request_id is not None:
                    row = connection.execute(
                        "SELECT * FROM messages WHERE source_tool_request_id = ?",
                        (source_tool_request_id,),
                    ).fetchone()
                if row is None:
                    raise
                return row, False

    def message_with_attachment(self, message_id: int) -> sqlite3.Row | None:
        """查询单条消息并 JOIN 其附件信息。"""
        return self.fetch_one(
            """
            SELECT m.*, a.original_name, a.stored_name, a.mime_type, a.size
            FROM messages m LEFT JOIN attachments a ON a.id = m.attachment_id
            WHERE m.id = ?
            """,
            (message_id,),
        )

    def messages_with_attachments(self, query: str, parameters: Iterable[object]) -> list[sqlite3.Row]:
        """执行自定义消息查询（通常含附件 JOIN）。"""
        return self.fetch_all(query, parameters)
