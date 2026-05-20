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

logger = get_logger("SwitchRouter")

_DATA_DIR = Config.KERNEL_DATA_DIR

# 安全的条件运算符白名单
_OP_FUNCS: dict[str, Any] = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
    "contains": lambda a, b: b in str(a),
}


class SwitchRouter(Router):
    """条件分支 Router —— 读取文件，按条件求真/假分支。

    纯机械逻辑，零 LLM 调用。

    读取守护文件内容，按 ``condition_field`` 点号路径提取字段值，
    用 ``condition_op`` 与 ``condition_value`` 求值。
    求值为真时写入 ``true_trigger`` 文件，为假时写入 ``false_trigger`` 文件。

    参数在构造时通过 ``**config`` 传入：
    - ``guard_pattern``: 守护的文件 glob 模式
    - ``condition_field``: 字段路径，如 ``"priority"`` 或 ``"payload.text"``
    - ``condition_op``: 运算符，见 ``_OP_FUNCS``
    - ``condition_value``: 比较目标值
    - ``true_trigger``: 真分支产物路径（相对于 KERNEL_DATA_DIR）
    - ``false_trigger``: 假分支产物路径
    """

    def __init__(self, node_id: str, **config: Any) -> None:
        super().__init__(node_id)
        self._guard_pattern = str(config.get("guard_pattern", "plans/plan_*.json"))
        self._condition_field = str(config.get("condition_field", "priority"))
        self._condition_op = str(config.get("condition_op", ">"))
        self._condition_value = config.get("condition_value", 50)
        self._true_trigger = str(
            config.get("true_trigger", "router/switch/true.trigger")
        )
        self._false_trigger = str(
            config.get("false_trigger", "router/switch/false.trigger")
        )

        if self._condition_op not in _OP_FUNCS:
            raise ValueError(
                f"SwitchRouter 不支持的条件运算符: {self._condition_op!r}。"
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
        return [
            FileDescriptor(self._true_trigger),
            FileDescriptor(self._false_trigger),
        ]

    async def execute(self) -> list[FileUpdate]:
        """扫描匹配文件，对每个文件评估条件并分发。"""
        guard_path = _DATA_DIR / self._guard_pattern
        parent = guard_path.parent
        pattern_name = guard_path.name

        if not parent.exists():
            return []

        matched = sorted(parent.glob(pattern_name))
        if not matched:
            return []

        updates: list[FileUpdate] = []
        for file_path in matched:
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(f"SwitchRouter 读取文件失败 {file_path}: {exc}")
                continue

            try:
                field_value = _resolve_field(data, self._condition_field)
                result = _OP_FUNCS[self._condition_op](
                    field_value, self._condition_value
                )
            except Exception as exc:
                logger.warning(
                    f"SwitchRouter 条件求值失败: field={self._condition_field}, "
                    f"op={self._condition_op}, value={self._condition_value!r}: {exc}"
                )
                continue

            trigger_path = self._true_trigger if result else self._false_trigger
            trigger_content = {
                "source_file": str(file_path.relative_to(_DATA_DIR)),
                "condition_field": self._condition_field,
                "condition_op": self._condition_op,
                "condition_value": self._condition_value,
                "field_value": field_value,
                "branch": "true" if result else "false",
            }

            updates.append(
                FileUpdate(
                    descriptor=FileDescriptor(
                        path=trigger_path,
                        schema="json",
                    ),
                    content=trigger_content,
                )
            )

            logger.debug(
                f"SwitchRouter: {file_path.name} → "
                f"{'true' if result else 'false'} "
                f"({self._condition_field} {self._condition_op} {self._condition_value!r})"
            )

        return updates

    def on_complete(self) -> None:
        if self.state != NodeState.ERROR:
            self.state = NodeState.IDLE


def _resolve_field(data: dict[str, Any], field_path: str) -> Any:
    """按点号分隔路径从嵌套 dict 中取值，如 ``"payload.text"``。"""
    current: Any = data
    for part in field_path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current
