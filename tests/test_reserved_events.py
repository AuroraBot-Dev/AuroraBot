"""保留事件（capability.*）只写因果事件与幂等回归。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.engine.store import SQLiteRuntimeStore

if TYPE_CHECKING:
    from pathlib import Path


def test_reserved_event_is_recorded_idempotently_and_not_inboxed(tmp_path: Path) -> None:
    store = SQLiteRuntimeStore(tmp_path / "runtime.sqlite3")
    store.initialize()

    assert (
        store.record_reserved_event(
            event_type="capability.registered",
            message_id="capability-message-1",
            summary="registered",
            payload={"capability_id": "aur.mcp.demo.tool"},
        )
        is True
    )
    assert (
        store.record_reserved_event(
            event_type="capability.registered",
            message_id="capability-message-1",
            summary="registered again",
            payload={"capability_id": "aur.mcp.demo.tool"},
        )
        is False
    )

    events = store.query_events(event_type="capability.registered")
    assert [event["summary"] for event in events] == ["registered"]
    assert store.counts()["inbox_events"] == 0
