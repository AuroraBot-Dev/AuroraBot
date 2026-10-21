"""主体规模增长后，查询和修改回执仍可按需读取。"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from aurora_bot.bot.inputs import StateInput
from aurora_bot.bot.views import change_view, state_view
from aurora_bot.contracts.bot import BotChange, BotSnapshot, Checkpoint, Goal, StateConflictError, WakePlan


def test_goal_index_is_paged_and_details_are_explicit() -> None:
    """很多长期检查点不会自动进入一次查询，全部内容仍可逐项展开。"""
    goals = tuple(
        Goal(f"aurora:goal/{index}", "长期目标" * 100, "已确认", checkpoint=Checkpoint(confirmed=("结果" * 1000,)))
        for index in range(25)
    )
    snapshot = BotSnapshot("aurora:bot/test", 7, goals)
    request = StateInput()
    size_limit = 1500
    first = state_view(snapshot, request)
    assert len(first["goals"]) == request.limit
    assert first["counts"]["goals"] == {"active": 25}
    assert first["page"]["next_offset"] == request.limit
    assert len(json.dumps(first, ensure_ascii=False)) < size_limit
    second = state_view(snapshot, StateInput(offset=10, limit=15, expected_version=7))
    assert second["goals"][0]["goal_id"] == goals[10].goal_id
    assert second["page"]["next_offset"] is None
    detail = state_view(snapshot, StateInput(goal_id=goals[24].goal_id))
    assert detail["goals"][0]["checkpoint"]["confirmed"] == list(goals[24].checkpoint.confirmed)
    mutation = change_view(snapshot, BotChange("changed", 6, (goals[24],)))
    assert [goal["goal_id"] for goal in mutation["goals"]] == [goals[24].goal_id]
    with pytest.raises(StateConflictError):
        state_view(snapshot, StateInput(offset=10, expected_version=6))


def test_wake_discovery_and_detail_keep_delivery_state() -> None:
    """安排索引保留身份、期限和状态，消息及核对细节按需展开。"""
    wake = WakePlan("aurora:wake/check", datetime(2026, 10, 18, tzinfo=UTC), "检查实验", detail="先核对操作身份")
    snapshot = BotSnapshot("aurora:bot/test", 1, wakes=(wake,))
    page = state_view(snapshot, StateInput(section="wakes"))
    assert page["wakes"][0]["status"] == "pending"
    assert "message" not in page["wakes"][0]
    detail = state_view(snapshot, StateInput(wake_id=wake.wake_id))
    assert detail["wakes"][0]["message"] == wake.message
    assert detail["wakes"][0]["detail"] == wake.detail
    assert change_view(snapshot, BotChange("wake", 0, wakes=(wake,)))["wakes"] == detail["wakes"]
    with pytest.raises(ValueError, match="每次只展开"):
        state_view(snapshot, StateInput(goal_id="aurora:goal/a", wake_id=wake.wake_id))
