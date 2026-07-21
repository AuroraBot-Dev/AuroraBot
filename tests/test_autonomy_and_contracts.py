from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from src.contracts.agent import AgentDecision, Completion
from src.contracts.configuration import AutonomyConfig
from src.contracts.memory import MemoryFailure, MemoryProposal, MemoryQuery, MemoryResult
from src.localhost.autonomy import AutonomyQuota

if TYPE_CHECKING:
    from pathlib import Path

_TOKENS = 42
_DEFAULT_MEMORY_LIMIT = 8
_DEFAULT_MEMORY_IMPORTANCE = 0.5


def test_autonomy_quota_tracks_usage_and_resets_daily(tmp_path: Path) -> None:
    current = datetime(2026, 7, 19, tzinfo=UTC)

    def clock() -> datetime:
        return current

    quota = AutonomyQuota(tmp_path / "quota.json", AutonomyConfig(autonomous_daily_model_calls=1), now=clock)
    assert quota.reserve_model_call()
    assert not quota.reserve_model_call()
    quota.record_tokens(_TOKENS)
    assert quota.status()["autonomous_tokens"] == _TOKENS
    current += timedelta(days=1)
    assert quota.status()["autonomous_model_calls"] == 0
    assert quota.status()["autonomous_tokens"] == 0


def test_agent_decision_and_memory_placeholder_contracts() -> None:
    decision = AgentDecision(completion=Completion("done", ({"uri": "artifact"},)))
    assert decision.completion is not None
    assert MemoryQuery("who", "global").limit == _DEFAULT_MEMORY_LIMIT
    assert MemoryResult(()).items == ()
    assert MemoryProposal({"fact": "x"}, "task").importance == _DEFAULT_MEMORY_IMPORTANCE
    assert MemoryFailure().code == "memory.unavailable"
