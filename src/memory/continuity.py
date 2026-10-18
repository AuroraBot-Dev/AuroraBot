"""选择当前任务的完整恢复状态，保留未展开状态的查询入口。"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from src.contracts.bot import GoalStatus, WakeStatus
from src.contracts.memory import MemoryContinuity
from src.utils.features import text_similarity

if TYPE_CHECKING:
    from src.contracts.bot import BotSnapshot
    from src.contracts.memory import MemoryRequest

_DEFAULT_FOCUS_LIMIT = 3


def select_continuity(snapshot: BotSnapshot, request: MemoryRequest) -> MemoryContinuity:
    """显式目标优先；没有焦点时按当前问题、待核对行动和活跃状态选择。"""
    available = {goal.goal_id: goal for goal in snapshot.goals}
    missing = tuple(identity for identity in request.focus_goal_ids if identity not in available)
    if request.focus_goal_ids:
        goals = tuple(available[identity] for identity in request.focus_goal_ids if identity in available)
    else:
        candidates = tuple(goal for goal in snapshot.goals if goal.status is GoalStatus.ACTIVE)
        goals = tuple(
            sorted(
                candidates,
                key=lambda goal: (
                    -text_similarity(request.query, f"{goal.purpose} {goal.checkpoint.stage}"),
                    not bool(goal.checkpoint.pending_actions),
                    goal.goal_id,
                ),
            )[:_DEFAULT_FOCUS_LIMIT]
        )
    focused = {goal.goal_id for goal in goals}
    wakes = tuple(wake for wake in snapshot.wakes if wake.goal_id is None or wake.goal_id in focused)
    running = tuple(wake for wake in wakes if wake.status is WakeStatus.RUNNING)
    pending = sorted(
        (wake for wake in wakes if wake.status is WakeStatus.PENDING), key=lambda wake: (wake.due_at, wake.wake_id)
    )
    return MemoryContinuity(
        snapshot.bot_id,
        snapshot.version,
        goals,
        (*running, *pending[:_DEFAULT_FOCUS_LIMIT]),
        tuple(sorted(Counter(goal.status.value for goal in snapshot.goals).items())),
        tuple(sorted(Counter(wake.status.value for wake in snapshot.wakes).items())),
        missing,
    )
