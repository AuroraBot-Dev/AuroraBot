"""SwitchRouter —— 条件分叉路由。

纯机械 Router 节点。watch 一个 glob，根据 config.routes 中的条件
将匹配的文件路由到不同的 emit 路径。

条件使用 ``state_store.resolve_field()`` + ``state_store.OP_FUNCS`` 运算符表。
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from src.kernel.base import FileDescriptor, FileUpdate, Router
from src.kernel.state_store import OP_FUNCS, kernel_data_dir, resolve_field
from src.utils.log_utils import get_logger

logger = get_logger("SwitchRouter")


class SwitchRouter(Router):
    """条件分叉路由。

    config.routes 格式::

        routes:
          - condition: "envelope.session_version > 5"
            emit: "pipeline/priority/gate_{envelope.id}.json"
          - condition: "payload.user_id contains 'admin'"
            emit: "pipeline/admin/gate_{envelope.id}.json"
          - default:
            emit: "pipeline/normal/gate_{envelope.id}.json"

    条件语法: ``字段名 运算符 值``，运算符来自 ``state_store.OP_FUNCS``。
    字段名可用点号访问嵌套字段（如 ``envelope.session_version``）。
    """

    _default_guards: list[str] = []  # noqa: RUF012 — 由 topology config 提供
    _default_produces: list[str] = []  # noqa: RUF012

    def __init__(
        self,
        node_id: str,
        host: "object | None" = None,
        *,
        routes: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)
        self._routes = routes or []

    async def execute(self) -> list[FileUpdate]:
        """扫描 watch 匹配的文件，按条件路由。"""
        if not self._config_watch:
            return []

        updates: list[FileUpdate] = []
        base_dir = kernel_data_dir

        for pattern in self._config_watch:
            for file_path in sorted(base_dir.glob(pattern), key=lambda p: p.name):
                try:
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(data, dict):
                    continue

                emit_path = self._evaluate(data)
                if not emit_path:
                    continue

                # 支持模板变量 {envelope.id} 等
                envelope = data.get("envelope", {}) if isinstance(data.get("envelope"), dict) else {}
                resolved = emit_path
                resolved = resolved.replace("{envelope.id}", str(envelope.get("id", "")))
                resolved = resolved.replace("{envelope.trace_id}", str(envelope.get("trace_id", "")))

                # 移除已路由的源文件（由 FileEventBus 的消费者负责 move_to_done，
                # 但这里做防御性删除以防重复处理）
                with contextlib.suppress(OSError):
                    file_path.unlink()

                update = FileUpdate(
                    descriptor=FileDescriptor(path=resolved, schema="json"),
                    content=data,
                )
                updates.append(update)
                logger.debug("路由: %s → %s (条件命中)", file_path.name, resolved)

        return updates

    def _evaluate(self, data: dict[str, Any]) -> str | None:
        """按路由规则评估，返回命中的 emit 路径。"""
        default_emit: str | None = None

        for route in self._routes:
            condition = route.get("condition")
            if condition is None:
                # default 规则
                default_emit = str(route.get("emit", ""))
                continue

            if self._match_condition(data, str(condition)):
                return str(route.get("emit", ""))

        return default_emit

    _CONDITION_PARTS = 3  # field_path op value

    @staticmethod
    def _match_condition(data: dict[str, Any], condition: str) -> bool:
        """评估单个条件表达式，如 'envelope.session_version > 5'。"""
        parts = condition.split(maxsplit=2)
        if len(parts) < SwitchRouter._CONDITION_PARTS:
            return False

        field_path, op, raw_value = parts[0], parts[1], parts[2]
        actual = resolve_field(data, field_path)

        if actual is None:
            return False

        # 尝试将 raw_value 转为合适的类型
        expect: Any = raw_value
        if raw_value.isdigit():
            expect = int(raw_value)
        elif raw_value.lower() in ("true", "false"):
            expect = raw_value.lower() == "true"
        elif raw_value.startswith('"') and raw_value.endswith('"'):
            expect = raw_value[1:-1]

        func = OP_FUNCS.get(op)
        if func is None:
            return False

        try:
            return bool(func(actual, expect))
        except (TypeError, ValueError):
            return False
