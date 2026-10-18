"""主体状态的显式持久化格式。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.contracts.bot import BotChange, Checkpoint, Goal, GoalStatus, WakePlan, WakeStatus

if TYPE_CHECKING:
    from collections.abc import Mapping


def goal_data(goal: Goal) -> dict[str, Any]:
    """将目标与恢复检查点编码为独立字段。"""
    checkpoint = goal.checkpoint
    return {
        "goal_id": goal.goal_id,
        "purpose": goal.purpose,
        "success_condition": goal.success_condition,
        "status": goal.status.value,
        "checkpoint": {
            "stage": checkpoint.stage,
            "confirmed": list(checkpoint.confirmed),
            "pending_actions": list(checkpoint.pending_actions),
            "constraints": list(checkpoint.constraints),
            "open_questions": list(checkpoint.open_questions),
            "evidence_refs": list(checkpoint.evidence_refs),
        },
    }


def read_goal(data: Mapping[str, Any]) -> Goal:
    """从已校验的持久记录恢复目标。"""
    checkpoint = data["checkpoint"]
    return Goal(
        goal_id=data["goal_id"],
        purpose=data["purpose"],
        success_condition=data["success_condition"],
        status=GoalStatus(data["status"]),
        checkpoint=Checkpoint(
            stage=checkpoint["stage"],
            confirmed=tuple(checkpoint["confirmed"]),
            pending_actions=tuple(checkpoint["pending_actions"]),
            constraints=tuple(checkpoint["constraints"]),
            open_questions=tuple(checkpoint["open_questions"]),
            evidence_refs=tuple(checkpoint["evidence_refs"]),
        ),
    )


def wake_data(wake: WakePlan) -> dict[str, Any]:
    """编码安排时间、所属目标与实际交付状态。"""
    return {
        "wake_id": wake.wake_id,
        "due_at": wake.due_at.isoformat(),
        "message": wake.message,
        "goal_id": wake.goal_id,
        "status": wake.status.value,
        "detail": wake.detail,
    }


def read_wake(data: Mapping[str, Any]) -> WakePlan:
    """恢复带时区的持久唤醒安排。"""
    return WakePlan(
        wake_id=data["wake_id"],
        due_at=datetime.fromisoformat(data["due_at"]),
        message=data["message"],
        goal_id=data["goal_id"],
        status=WakeStatus(data["status"]),
        detail=data["detail"],
    )


def change_data(change: BotChange) -> dict[str, Any]:
    """编码命令身份、读取版本与整组原子修改。"""
    return {
        "command_id": change.command_id,
        "expected_version": change.expected_version,
        "goals": [goal_data(goal) for goal in change.goals],
        "wakes": [wake_data(wake) for wake in change.wakes],
    }
