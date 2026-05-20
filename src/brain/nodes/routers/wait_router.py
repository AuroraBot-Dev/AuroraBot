from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.brain.kernel.base import (
    FileDescriptor,
    FilePattern,
    FileUpdate,
    NodeState,
    Router,
)
from src.config import Config
from src.utils.log_utils import get_logger

logger = get_logger("WaitRouter")

_DATA_DIR = Config.KERNEL_DATA_DIR

# 与 SwitchRouter 共用安全运算符
_OP_FUNCS: dict[str, Any] = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
}


class WaitRouter(Router):
    """条件等待 Router —— 等待文件内容满足条件后产出就绪信号。

    纯机械逻辑，零 LLM 调用。不自旋——靠文件事件唤醒。

    守护一个文件模式，每次匹配文件变更时唤醒。
    ``execute()`` 中检查文件内容是否满足条件：
    - 满足 → 写入 ``ready_trigger`` 信号文件，激活下游
    - 不满足 → 返回空，回到 IDLE 等待下次事件

    参数在构造时通过 ``**config`` 传入：
    - ``guard_pattern``: 守护的文件 glob 模式
    - ``condition_field``: 字段路径，如 ``"status"``
    - ``condition_op``: 运算符
    - ``condition_value``: 期望值
    - ``ready_trigger``: 就绪信号文件路径
    - ``require_all``: 是否要求所有匹配文件都满足条件（默认 False，任一满足即触发）
    """

    def __init__(self, node_id: str, **config: Any) -> None:
        super().__init__(node_id)
        self._guard_pattern = str(config.get("guard_pattern", "plans/plan_*.json"))
        self._condition_field = str(config.get("condition_field", "status"))
        self._condition_op = str(config.get("condition_op", "=="))
        self._condition_value = config.get("condition_value", "done")
        self._ready_trigger = str(
            config.get("ready_trigger", "router/wait/ready.trigger")
        )
        self._require_all = bool(config.get("require_all", False))

        if self._condition_op not in _OP_FUNCS:
            raise ValueError(
                f"WaitRouter 不支持的条件运算符: {self._condition_op!r}。"
                f" 支持: {sorted(_OP_FUNCS)}"
            )

    @property
    def type(self) -> str:
        return "router"

    @property
    def guards(self) -> list[FilePattern]:
        if self._config_watch is not None:
            return [FilePattern(p) for p in self._config_watch]
        return [FilePattern(self._guard_pattern)]

    @property
    def produces(self) -> list[FileDescriptor]:
        if self._config_emit is not None:
            return [FileDescriptor(p) for p in self._config_emit]
        return [FileDescriptor(self._ready_trigger)]

    async def execute(self) -> list[FileUpdate]:
        """检查文件条件，满足时产出就绪信号。"""
        guard_path = _DATA_DIR / self._guard_pattern
        parent = guard_path.parent
        pattern_name = guard_path.name

        if not parent.exists():
            return []

        matched = sorted(parent.glob(pattern_name))
        if not matched:
            return []

        satisfied: list[Path] = []
        for file_path in matched:
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue
            except (OSError, json.JSONDecodeError):
                continue

            try:
                field_value = _resolve_field(data, self._condition_field)
                if _OP_FUNCS[self._condition_op](field_value, self._condition_value):
                    satisfied.append(file_path)
            except Exception:
                continue

        if not satisfied:
            return []

        if self._require_all and len(satisfied) < len(matched):
            logger.debug(
                f"WaitRouter: {len(satisfied)}/{len(matched)} 满足条件，继续等待"
            )
            return []

        ready_content = {
            "condition_field": self._condition_field,
            "condition_op": self._condition_op,
            "condition_value": self._condition_value,
            "matched_files": [str(p.relative_to(_DATA_DIR)) for p in satisfied],
            "satisfied_count": len(satisfied),
            "total_count": len(matched),
        }

        logger.info(
            f"WaitRouter: 条件满足 "
            f"({self._condition_field} {self._condition_op} {self._condition_value!r})，"
            f" {len(satisfied)}/{len(matched)} 文件达标"
        )

        return [
            FileUpdate(
                descriptor=FileDescriptor(
                    path=self._ready_trigger,
                    schema="json",
                ),
                content=ready_content,
            )
        ]

    def on_complete(self) -> None:
        if self.state != NodeState.ERROR:
            self.state = NodeState.IDLE


def _resolve_field(data: dict[str, Any], field_path: str) -> Any:
    """按点号分隔路径从嵌套 dict 中取值。"""
    current: Any = data
    for part in field_path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current
