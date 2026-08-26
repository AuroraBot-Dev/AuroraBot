from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ops.panel import PanelStore


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def test_panel_store_creates_token_and_persists_only_session_digest(tmp_path: Path) -> None:
    async def scenario() -> None:
        tokens = iter(("bootstrap-secret", "session-secret"))
        clock = MutableClock(datetime(2026, 8, 26, 12, tzinfo=UTC))
        store = PanelStore(
            tmp_path,
            session_ttl_seconds=60,
            clock=clock,
            token_factory=lambda: next(tokens),
        )

        await store.initialize()
        session = await store.create_session("bootstrap-secret")

        assert store.token_created is True
        assert store.token_path.read_text(encoding="utf-8") == "bootstrap-secret"
        assert session is not None
        assert session.token == "session-secret"
        assert session.created_at == clock.value
        assert session.expires_at == clock.value + timedelta(seconds=60)
        assert await store.verify_session(session.token) is True
        assert await store.create_session("wrong-token") is None
        await store.close()

        with sqlite3.connect(store.database_path) as connection:
            rows = connection.execute("SELECT token_digest, created_at, expires_at FROM sessions").fetchall()
        assert rows == [
            (
                hashlib.sha256(b"session-secret").hexdigest(),
                "2026-08-26T12:00:00+00:00",
                "2026-08-26T12:01:00+00:00",
            )
        ]
        database = store.database_path.read_bytes()
        assert b"session-secret" not in database

    asyncio.run(scenario())
    assert not tuple(tmp_path.glob(".Token.*.tmp"))


def test_panel_store_reuses_token_expires_and_deletes_sessions(tmp_path: Path) -> None:
    async def scenario() -> None:
        (tmp_path / "Token.txt").write_text("existing-bootstrap\n", encoding="utf-8")
        tokens = iter(("session-one", "session-two"))
        clock = MutableClock(datetime(2026, 8, 26, 12, tzinfo=UTC))
        store = PanelStore(tmp_path, session_ttl_seconds=10, clock=clock, token_factory=lambda: next(tokens))

        await store.initialize()
        first = await store.create_session("existing-bootstrap")
        second = await store.create_session("existing-bootstrap")

        assert store.token_created is False
        assert first is not None and second is not None
        assert await store.delete_session(first.token) is True
        assert await store.delete_session(first.token) is False
        clock.value += timedelta(seconds=10)
        assert await store.verify_session(second.token) is False
        await store.close()

    asyncio.run(scenario())


def test_empty_bootstrap_token_is_replaced_and_revokes_old_sessions(tmp_path: Path) -> None:
    async def scenario() -> None:
        first_tokens = iter(("bootstrap-one", "session-one"))
        first = PanelStore(tmp_path, session_ttl_seconds=60, token_factory=lambda: next(first_tokens))
        await first.initialize()
        session = await first.create_session("bootstrap-one")
        assert session is not None
        await first.close()

        (tmp_path / "Token.txt").write_text("\n", encoding="utf-8")
        second = PanelStore(tmp_path, session_ttl_seconds=60, token_factory=lambda: "bootstrap-two")
        await second.initialize()

        assert second.token_created is True
        assert second.bootstrap_token == "bootstrap-two"
        assert await second.verify_session(session.token) is False
        await second.close()

    asyncio.run(scenario())


def test_panel_store_requires_absolute_directory_and_aware_clock(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="绝对路径"):
        PanelStore(Path("relative"), session_ttl_seconds=1)

    async def scenario() -> None:
        tokens = iter(("bootstrap", "session"))
        store = PanelStore(
            tmp_path,
            session_ttl_seconds=1,
            clock=lambda: datetime(2026, 8, 26, tzinfo=UTC).replace(tzinfo=None),
            token_factory=lambda: next(tokens),
        )
        await store.initialize()
        with pytest.raises(ValueError, match="含时区"):
            await store.create_session("bootstrap")
        await store.close()

    asyncio.run(scenario())
