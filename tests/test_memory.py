# ruff: noqa: PLR2004
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from src.contracts.memory import MemoryEntry, MemoryFailure, MemoryProposal, MemoryQuery, MemoryResult
from src.memory.service import MemoryService

if TYPE_CHECKING:
    from pathlib import Path


def test_memory_placeholder_contracts() -> None:
    assert MemoryQuery("who", "global").limit == 8
    assert MemoryResult(()).items == ()
    assert MemoryProposal({"fact": "x"}, "task").importance == 0.5
    assert MemoryFailure().code == "memory.unavailable"


def test_disabled_service_uses_the_memory_store_contract() -> None:
    service = MemoryService.disabled()
    assert not service.available
    assert service.recall("anything").recent_conversation == ()
    assert service.recall("anything").related_memories == ()
    assert not service.remember(MemoryEntry("task", "hello", "hi", "2026-01-01T00:00:00Z"))


def test_remember_is_idempotent_and_recall_reads_completed_private_ledger(tmp_path: Path) -> None:
    engine_dir = tmp_path / "engine" / "process"
    engine_dir.mkdir(parents=True)
    with sqlite3.connect(engine_dir / "runtime.sqlite3") as connection:
        connection.execute("CREATE TABLE causal_events(summary TEXT)")
        connection.execute("INSERT INTO causal_events VALUES ('engine-only event')")

    memory_dir = tmp_path / "memory"
    service = MemoryService(memory_dir=memory_dir)
    assert service.recall("engine-only event").recent_conversation == ()
    first = MemoryEntry("task-1", "first question", "first answer", "2026-01-01T00:00:00Z")
    duplicate = MemoryEntry("task-1", "changed question", "changed answer", "2026-01-03T00:00:00Z")
    second = MemoryEntry("task-2", "second question", None, "2026-01-02T00:00:00Z")

    assert service.remember(first)
    assert not service.remember(duplicate)
    assert service.remember(second)
    with sqlite3.connect(memory_dir / "memory.sqlite3") as connection:
        connection.execute("CREATE TABLE pending_tasks(user_text TEXT, assistant_text TEXT, created_at TEXT)")
        connection.execute("INSERT INTO pending_tasks VALUES ('pending question', 'pending answer', '2026-01-04')")

    recalled = service.recall("question")
    assert [(turn.user, turn.assistant) for turn in recalled.recent_conversation] == [
        ("first question", "first answer"),
        ("second question", None),
    ]
    assert recalled.related_memories == ()


def test_private_ledger_errors_are_nonfatal(tmp_path: Path) -> None:
    (tmp_path / "memory.sqlite3").mkdir()
    service = MemoryService(memory_dir=tmp_path)
    assert service.recall("anything").recent_conversation == ()
