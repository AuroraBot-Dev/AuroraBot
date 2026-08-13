"""面板私有存储：Token 原子创建、会话生命周期与附件索引。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from ops.store import PanelStore


def test_bootstrap_token_created_once_with_restricted_mode(tmp_path: Path) -> None:
    data_dir = tmp_path / "ops"
    store = PanelStore(data_dir)
    token = store.bootstrap_token
    assert token and store.bootstrap_token == token

    token_path = data_dir / "Token.txt"
    assert token_path.exists()
    assert token_path.read_text(encoding="utf-8").strip() == token
    assert token_path.stat().st_mode & 0o077 == 0

    store.close()

    reopened = PanelStore(data_dir)
    assert reopened.bootstrap_token == token
    reopened.close()


def test_session_create_verify_delete(tmp_path: Path) -> None:
    store = PanelStore(tmp_path / "ops")
    meta = store.create_session("token-abc", ttl_seconds=3600)
    assert meta["expires_at"] > meta["created_at"]
    assert store.verify_session("token-abc")
    assert not store.verify_session("wrong")

    store.delete_session("token-abc")
    assert not store.verify_session("token-abc")
    store.close()


def test_sessions_are_stored_as_digests(tmp_path: Path) -> None:
    store = PanelStore(tmp_path / "ops")
    store.create_session("plain-text-token", ttl_seconds=3600)
    database = (tmp_path / "ops" / "panel.sqlite3").read_text(encoding="utf-8", errors="ignore")
    assert "plain-text-token" not in database
    store.close()


def test_attachment_index_roundtrip(tmp_path: Path) -> None:
    store = PanelStore(tmp_path / "ops")
    record = store.add_attachment(name="a.txt", mime="text/plain", size=3, stored_name="stored-1")
    assert record["attachment_id"]
    fetched = store.get_attachment(record["attachment_id"])
    assert fetched is not None
    assert fetched["name"] == "a.txt"
    assert fetched["mime"] == "text/plain"
    assert fetched["size"] == 3  # noqa: PLR2004
    assert store.get_attachment("missing") is None
    store.close()
