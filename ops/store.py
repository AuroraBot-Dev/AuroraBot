"""面板后端私有存储（RFC 0218 §6）：bootstrap Token、Bearer 会话与附件索引。

位于 ops 包，数据落 ``data/ops/``（panel.sqlite3 + Token.txt + uploads/）。
仅使用 stdlib sqlite3，保持 ops 只依赖 contracts + utils 的边界。
"""

from __future__ import annotations

import secrets
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_SCHEMA_VERSION = 1
_TOKEN_BYTES = 32


class PanelStore:
    """面板会话与附件存储：Token 文件原子创建、会话生命周期与附件索引。"""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        self._database_path = data_dir / "panel.sqlite3"
        self._token_path = data_dir / "Token.txt"
        self._upload_dir = data_dir / "uploads"
        self._upload_dir.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._database_path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=30000")
        self._migrate()
        self._bootstrap_token = self._load_or_create_token()

    @property
    def bootstrap_token(self) -> str:
        """本次启动的 bootstrap token（首次启动生成并落盘）。"""
        return self._bootstrap_token

    @property
    def upload_dir(self) -> Path:
        return self._upload_dir

    def _load_or_create_token(self) -> str:
        """读取或原子创建 Token.txt（0600）。"""
        if self._token_path.exists():
            raw = self._token_path.read_text(encoding="utf-8").strip()
            if raw:
                return raw
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        temporary = self._token_path.with_suffix(".tmp")
        temporary.write_text(token + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(self._token_path)
        return token

    def _migrate(self) -> None:
        """Schema v1 迁移：sessions 与 attachments 表。"""
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        if version == _SCHEMA_VERSION:
            return
        if version not in (0, 1):
            raise RuntimeError(f"unsupported panel schema version: {version}")
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS attachments (
                    attachment_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    mime TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    stored_name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute("PRAGMA user_version = 1")

    @contextmanager
    def _session(self) -> Generator[sqlite3.Connection]:
        """事务上下文：成功提交，异常回滚。"""
        connection = self._connection
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    # -- 认证 ------------------------------------------------------------

    def create_session(self, token: str, ttl_seconds: int) -> dict[str, str]:
        """为登录 token 创建 Bearer 会话，返回会话元数据。"""
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=ttl_seconds)
        with self._session() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO sessions(token_hash, created_at, expires_at) VALUES (?, ?, ?)",
                (_digest(token), now.isoformat(), expires.isoformat()),
            )
        return {"created_at": now.isoformat(), "expires_at": expires.isoformat()}

    def verify_session(self, token: str) -> bool:
        """校验 Bearer token：存在且未过期。"""
        now = datetime.now(UTC).isoformat()
        with self._session() as connection:
            row = connection.execute(
                "SELECT expires_at FROM sessions WHERE token_hash = ?", (_digest(token),)
            ).fetchone()
        return row is not None and row[0] > now

    def delete_session(self, token: str) -> None:
        """销毁会话。"""
        with self._session() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (_digest(token),))

    # -- 附件 ------------------------------------------------------------

    def add_attachment(self, *, name: str, mime: str, size: int, stored_name: str) -> dict[str, Any]:
        """登记附件并返回索引记录。"""
        attachment_id = str(uuid4().hex)
        created_at = datetime.now(UTC).isoformat()
        with self._session() as connection:
            connection.execute(
                "INSERT INTO attachments(attachment_id, name, mime, size, stored_name, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (attachment_id, name, mime, size, stored_name, created_at),
            )
        return self._attachment_row(attachment_id, name, mime, size, stored_name, created_at)

    def get_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        """按 ID 查询附件索引。"""
        with self._session() as connection:
            row = connection.execute(
                "SELECT attachment_id, name, mime, size, stored_name, created_at "
                "FROM attachments WHERE attachment_id = ?",
                (attachment_id,),
            ).fetchone()
        return self._attachment_row(*row) if row is not None else None

    @staticmethod
    def _attachment_row(
        attachment_id: str, name: str, mime: str, size: int, stored_name: str, created_at: str
    ) -> dict[str, Any]:
        return {
            "attachment_id": attachment_id,
            "name": name,
            "mime": mime,
            "size": size,
            "stored_name": stored_name,
            "created_at": created_at,
        }

    def close(self) -> None:
        """关闭数据库连接。"""
        self._connection.close()


def _digest(token: str) -> str:
    """会话 token 的 SHA-256 摘要（库中不存明文）。"""
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()
