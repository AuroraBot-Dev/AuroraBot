"""适合按需读取的主体视图，完整持久状态保留在主体存储中。"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from src.bot.codec import goal_data, wake_data
from src.contracts.bot import StateConflictError

if TYPE_CHECKING:
    from src.bot.inputs import StateInput
    from src.contracts.bot import BotChange, BotSnapshot


def state_view(snapshot: BotSnapshot, request: StateInput) -> dict[str, Any]:
    """分页只展示身份和状态；精确读取才返回完整检查点或安排。"""
    if request.expected_version is not None and request.expected_version != snapshot.version:
        raise StateConflictError(f"主体版本已变化：预期 {request.expected_version}，当前 {snapshot.version}")
    if request.goal_id is not None and request.wake_id is not None:
        raise ValueError("每次只展开一个目标或一项安排")
    data = _header(snapshot)
    if request.goal_id is not None:
        return {**data, "view": "detail", "goals": [goal_data(snapshot.goal(request.goal_id))]}
    if request.wake_id is not None:
        return {**data, "view": "detail", "wakes": [wake_data(snapshot.wake(request.wake_id))]}
    if request.section == "goals":
        entries = [{"goal_id": goal.goal_id, "status": goal.status.value} for goal in snapshot.goals]
    else:
        entries = [
            {
                "wake_id": wake.wake_id,
                "status": wake.status.value,
                "due_at": wake.due_at.isoformat(),
                "goal_id": wake.goal_id,
            }
            for wake in snapshot.wakes
        ]
    end = min(len(entries), request.offset + request.limit)
    data[request.section] = entries[request.offset : end]
    return {
        **data,
        "view": "index",
        "page": {
            "section": request.section,
            "offset": request.offset,
            "limit": request.limit,
            "total": len(entries),
            "next_offset": end if end < len(entries) else None,
        },
    }


def change_view(snapshot: BotSnapshot, change: BotChange) -> dict[str, Any]:
    """修改回执只展开明确提交的对象，避免重复附带全部经历。"""
    return {
        **_header(snapshot),
        "view": "change",
        "goals": [goal_data(snapshot.goal(goal.goal_id)) for goal in change.goals],
        "wakes": [wake_data(snapshot.wake(wake.wake_id)) for wake in change.wakes],
    }


def _header(snapshot: BotSnapshot) -> dict[str, Any]:
    """披露完整状态规模和版本，提供进一步查询的依据。"""
    return {
        "bot_id": snapshot.bot_id,
        "version": snapshot.version,
        "counts": {
            "goals": dict(Counter(goal.status.value for goal in snapshot.goals)),
            "wakes": dict(Counter(wake.status.value for wake in snapshot.wakes)),
        },
        "goals": [],
        "wakes": [],
    }
