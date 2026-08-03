# ruff: noqa: PLR2004
from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts.memory import MemoryEntry, MemoryQuery
from src.memory.service import MemoryService

if TYPE_CHECKING:
    from pathlib import Path


def test_disabled_service_uses_the_memory_store_contract() -> None:
    service = MemoryService.disabled()
    assert not service.available
    assert service.recall(MemoryQuery("anything", "session")).session_summary == ""
    assert not service.remember(MemoryEntry("task", "session", "hello", "hi", "2026-01-01"))


def test_memory_is_idempotent_session_scoped_and_fact_bounded(tmp_path: Path) -> None:
    service = MemoryService(tmp_path)
    first = MemoryEntry(
        "task-1",
        "session",
        "用户：first question",
        "first answer",
        "2026-01-01",
        ("user prefers concise answers",),
    )
    duplicate = MemoryEntry("task-1", "session", "changed", "changed", "2026-01-03")
    second = MemoryEntry("task-2", "session", "用户：second question", None, "2026-01-02")
    other = MemoryEntry("task-3", "other", "用户：other", "other answer", "2026-01-04")

    assert service.remember(first)
    assert not service.remember(duplicate)
    assert service.remember(second)
    assert service.remember(other)

    recalled = service.recall(MemoryQuery("concise", "session", fact_limit=1))
    assert "first question" in recalled.session_summary
    assert "second question" in recalled.session_summary
    assert "other answer" not in recalled.session_summary
    assert recalled.relevant_facts == ("user prefers concise answers",)


def test_memory_snapshot_obeys_total_character_budget(tmp_path: Path) -> None:
    service = MemoryService(tmp_path)
    assert service.remember(MemoryEntry("one", "session", "x" * 100, "y" * 100, "2026-01-01", ("z" * 100,)))
    recalled = service.recall(MemoryQuery("query", "session", max_characters=32))
    assert len(recalled.session_summary) + sum(map(len, recalled.relevant_facts)) <= 32
