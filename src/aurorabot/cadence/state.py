"""节律消费者的持久游标、安排与显式模型状态。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from aurorabot.contracts import TreeLaunchRequest, WorldFrontier
from aurorabot.contracts.resource import ResourceKey, ResourceRef

if TYPE_CHECKING:
    from collections.abc import Mapping

    from aurorabot.contracts.rhythm import RhythmDecision, RhythmObservation


@dataclass(frozen=True, slots=True)
class CadenceState:
    """从最后一次判断恢复 Bot 的节奏，不重新解释认知运行。"""

    cursor: int
    pending: int
    last_deliberated_at: datetime
    next_check_at: datetime
    hidden: tuple[float, ...] = ()
    reactive_commit: str | None = None
    reactive_agent: str | None = None
    failed_runs: int = 0

    def __post_init__(self) -> None:
        """在构造边界校验自己的计数、时间和数值状态。"""
        if min(self.cursor, self.pending, self.failed_runs) < 0:
            raise ValueError("节律状态计数不能小于零")
        for value in (self.last_deliberated_at, self.next_check_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("节律状态时间必须包含时区")
        if any(not math.isfinite(value) for value in self.hidden):
            raise ValueError("节律隐状态必须由有限数值组成")
        object.__setattr__(self, "hidden", tuple(self.hidden))

    def data(self) -> dict[str, Any]:
        """状态只使用可稳定编码的基础类型。"""
        return {
            "cursor": self.cursor,
            "pending": self.pending,
            "last_deliberated_at": self.last_deliberated_at.isoformat(),
            "next_check_at": self.next_check_at.isoformat(),
            "hidden": list(self.hidden),
            "reactive_commit": self.reactive_commit,
            "reactive_agent": self.reactive_agent,
            "failed_runs": self.failed_runs,
        }

    @classmethod
    def restore(cls, data: Mapping[str, Any]) -> CadenceState:
        """恢复时核对时间与状态数值，日志损坏时明确失败。"""
        return cls(
            data["cursor"],
            data["pending"],
            datetime.fromisoformat(data["last_deliberated_at"]),
            datetime.fromisoformat(data["next_check_at"]),
            tuple(data["hidden"]),
            data["reactive_commit"],
            data["reactive_agent"],
            data.get("failed_runs", 0),
        )


def observation_data(observation: RhythmObservation) -> dict[str, Any]:
    """保留输入特征及可还原的业务坐标，供训练与回放使用。"""
    return {
        "bot_id": observation.bot_id,
        "observed_at": observation.observed_at.isoformat(),
        "cursor": observation.cursor,
        "pending_events": observation.pending_events,
        "elapsed_seconds": observation.elapsed_seconds,
        "active_goal_ids": list(observation.active_goal_ids),
        "pending_actions": observation.pending_actions,
        "failed_wakes": observation.failed_wakes,
        "timer_due": observation.timer_due,
        "reactive_event": observation.reactive_event,
        "features": list(observation.features()),
    }


def decision_data(decision: RhythmDecision) -> dict[str, Any]:
    """等待与推理都记录完整的策略选择。"""
    return {
        "action": decision.action.value,
        "next_check_at": decision.next_check_at.isoformat(),
        "reason": decision.reason,
        "focus_goal_ids": list(decision.focus_goal_ids),
        "probability": decision.probability,
    }


def read_reference(data: Mapping[str, Any]) -> ResourceRef:
    """读取记录中被冻结的策略版本。"""
    return ResourceRef(ResourceKey.parse(data["key"]), data["revision"])


def launch_data(request: TreeLaunchRequest) -> dict[str, Any]:
    """记录重启前尚未启动的认知请求。"""
    return {
        "message": request.message,
        "tree_id": request.tree_id,
        "agent": request.agent,
        "frontier": dict(request.frontier.positions),
        "caused_by": request.caused_by,
        "memory_scopes": sorted(request.memory_scopes) if request.memory_scopes is not None else None,
        "focus_goal_ids": list(request.focus_goal_ids),
    }


def read_launch(data: Mapping[str, Any]) -> TreeLaunchRequest:
    """重启恢复使用原来的运行身份和触发事实。"""
    return TreeLaunchRequest(
        data["message"],
        data["tree_id"],
        data["agent"],
        WorldFrontier(data["frontier"]),
        data["caused_by"],
        frozenset(data["memory_scopes"]) if data["memory_scopes"] is not None else None,
        tuple(data.get("focus_goal_ids", ())),
    )
