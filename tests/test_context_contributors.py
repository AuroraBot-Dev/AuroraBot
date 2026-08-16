"""ContextContributor 快照合并的确定性回归。"""

from __future__ import annotations

from src.contracts import (
    MemoryContextSnapshot,
    MemoryMessage,
    RemoteMessage,
    RemoteSummary,
)
from src.engine.runtime import _merge_context_snapshots


def _snapshot(*, suffix: str = "", facts: tuple[str, ...] = ()) -> MemoryContextSnapshot:
    return MemoryContextSnapshot(
        summary=f"summary{suffix}" if suffix else "",
        window=(MemoryMessage("user", f"hello{suffix}", "2026-01-01T00:00:00"),),
        remote_summaries=(RemoteSummary(f"scope{suffix}", f"remote{suffix}", "2026-01-01T00:00:00"),),
        remote_window=(RemoteMessage(f"scope{suffix}", "assistant", f"tail{suffix}", "2026-01-01T00:00:00"),),
        relevant_facts=facts,
    )


def test_merge_handles_empty_and_single_snapshots() -> None:
    assert _merge_context_snapshots(()) == MemoryContextSnapshot()
    snapshot = _snapshot(suffix="a", facts=("fact-a",))
    assert _merge_context_snapshots((snapshot,)) is snapshot


def test_merge_joins_fields_and_deduplicates_facts() -> None:
    merged = _merge_context_snapshots(
        (_snapshot(suffix="a", facts=("shared", "a")), _snapshot(suffix="b", facts=("shared", "b")))
    )

    assert merged.summary == "summarya\n\nsummaryb"
    assert [item.content for item in merged.window] == ["helloa", "hellob"]
    assert [item.scope for item in merged.remote_summaries] == ["scopea", "scopeb"]
    assert [item.scope for item in merged.remote_window] == ["scopea", "scopeb"]
    assert merged.relevant_facts == ("shared", "a", "b")
