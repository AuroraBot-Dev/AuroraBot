"""Panel bootstrap Token 与短期 session 的本地持久化。"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import tempfile
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite

from ops.panel.contracts import PanelSession

if TYPE_CHECKING:
    from collections.abc import Callable

_TOKEN_BYTES = 32
_TOKEN_FILE = "Token.txt"
_DATABASE_FILE = "panel.sqlite3"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _random_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


class PanelStore:
    def __init__(
        self,
        directory: Path,
        *,
        session_ttl_seconds: int,
        clock: Callable[[], datetime] = _utc_now,
        token_factory: Callable[[], str] = _random_token,
    ) -> None:
        if not directory.is_absolute():
            raise ValueError("PanelStore directory 必须是绝对路径")
        if session_ttl_seconds <= 0:
            raise ValueError("session_ttl_seconds 必须大于 0")
        self._directory = directory
        self._session_ttl = timedelta(seconds=session_ttl_seconds)
        self._clock = clock
        self._token_factory = token_factory
        self._connection: aiosqlite.Connection | None = None
        self._bootstrap_token: str | None = None
        self._token_created = False

    @property
    def directory(self) -> Path:
        return self._directory

    @property
    def token_path(self) -> Path:
        return self._directory / _TOKEN_FILE

    @property
    def database_path(self) -> Path:
        return self._directory / _DATABASE_FILE

    @property
    def bootstrap_token(self) -> str:
        if self._bootstrap_token is None:
            raise RuntimeError("PanelStore 尚未初始化")
        return self._bootstrap_token

    @property
    def token_created(self) -> bool:
        return self._token_created

    async def initialize(self) -> None:
        if self._connection is not None:
            return
        self._directory.mkdir(parents=True, exist_ok=True)
        token, created = self._load_or_create_bootstrap_token()
        connection = await aiosqlite.connect(self.database_path)
        try:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token_digest TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            if created:
                await connection.execute("DELETE FROM sessions")
            await connection.commit()
        except BaseException:
            await connection.close()
            raise
        self._bootstrap_token = token
        self._token_created = created
        self._connection = connection

    async def close(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            await connection.close()

    async def create_session(self, token_login: str) -> PanelSession | None:
        connection = self._require_connection()
        candidate = token_login if isinstance(token_login, str) else ""
        if not hmac.compare_digest(candidate, self.bootstrap_token):
            return None
        created_at = self._now()
        expires_at = created_at + self._session_ttl
        await connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (created_at.isoformat(),))
        for _ in range(3):
            token = self._token_factory()
            if not token or hmac.compare_digest(token, self.bootstrap_token):
                continue
            try:
                await connection.execute(
                    "INSERT INTO sessions (token_digest, created_at, expires_at) VALUES (?, ?, ?)",
                    (_digest(token), created_at.isoformat(), expires_at.isoformat()),
                )
            except aiosqlite.IntegrityError:
                continue
            await connection.commit()
            return PanelSession(token, created_at, expires_at)
        await connection.rollback()
        raise RuntimeError("无法生成唯一的 Panel session token")

    async def verify_session(self, token: str) -> bool:
        if not token:
            return False
        connection = self._require_connection()
        cursor = await connection.execute(
            "SELECT expires_at FROM sessions WHERE token_digest = ?",
            (_digest(token),),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return False
        if datetime.fromisoformat(str(row[0])) > self._now():
            return True
        await connection.execute("DELETE FROM sessions WHERE token_digest = ?", (_digest(token),))
        await connection.commit()
        return False

    async def delete_session(self, token: str) -> bool:
        if not token:
            return False
        connection = self._require_connection()
        cursor = await connection.execute("DELETE FROM sessions WHERE token_digest = ?", (_digest(token),))
        deleted = cursor.rowcount > 0
        await cursor.close()
        await connection.commit()
        return deleted

    def _load_or_create_bootstrap_token(self) -> tuple[str, bool]:
        try:
            token = self.token_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            token = ""
        if token:
            _restrict_permissions(self.token_path)
            return token, False
        token = self._token_factory()
        if not token:
            raise RuntimeError("无法生成 Panel bootstrap Token")
        descriptor, temporary_name = tempfile.mkstemp(prefix=".Token.", suffix=".tmp", dir=self._directory)
        temporary_path = Path(temporary_name)
        try:
            _restrict_permissions(temporary_path)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                descriptor = -1
                stream.write(token)
                stream.flush()
                os.fsync(stream.fileno())
            temporary_path.replace(self.token_path)
            _restrict_permissions(self.token_path)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary_path.unlink(missing_ok=True)
        return token, True

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("PanelStore clock 必须返回含时区时间")
        return value.astimezone(UTC)

    def _require_connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("PanelStore 尚未初始化")
        return self._connection


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _restrict_permissions(path: Path) -> None:
    with suppress(OSError):
        path.chmod(0o600)
