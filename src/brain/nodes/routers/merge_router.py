"""MergeRouter —— 多源汇聚路由。

纯机械 Router 节点。watch 多个 glob 路径，按 config.strategy 等待条件满足后触发。
支持 "all"（所有源都有文件）和 "any"（任一源有文件）两种策略。

典型用途：等待「门控通过」+「记忆检索完成」两个条件都满足后触发下游。
"""

from __future__ import annotations

import json
from typing import Any

from src.brain.kernel.base import FileDescriptor, FileEvent, FileUpdate, NodeState, Router
from src.brain.kernel.state_store import kernel_data_dir, move_to_done, next_record_id
from src.utils.log_utils import get_logger

logger = get_logger("MergeRouter")


class MergeRouter(Router):
    """多源汇聚路由。

    config 格式::

        strategy: all           # "all" | "any"
        match_by: "envelope.session_key"   # 可选：按字段配对文件
        merge_mode: "concat"    # "concat" | "first"

    当 strategy="all" 时，所有 watch 的 glob 都必须至少有一个文件存在才触发。
    当 strategy="any" 时，任一 glob 有文件就触发。
    """

    _default_guards: list[str] = []  # noqa: RUF012 — 由 topology config 提供
    _default_produces: list[str] = []  # noqa: RUF012

    def __init__(
        self,
        node_id: str,
        host: "object | None" = None,
        *,
        strategy: str = "all",
        match_by: str | None = None,
        merge_mode: str = "concat",
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)
        self._strategy = strategy
        self._match_by = match_by
        self._merge_mode = merge_mode
        self._source_files: dict[str, list[str]] = {}

    def on_event(self, event: FileEvent) -> bool:
        """覆写：所有源都有文件时才激活。"""
        if self.state not in (NodeState.IDLE, NodeState.READY):
            return False

        # 检查事件是否匹配任一 guard
        matched_guard = None
        for i, guard in enumerate(self.guards):
            if guard.match(event.path):
                matched_guard = i
                break
        if matched_guard is None:
            return False

        if self._strategy == "any":
            return True

        # "all" strategy: 检查所有源是否都有文件
        base = kernel_data_dir
        for guard in self.guards:
            pattern = guard.pattern
            try:
                hits = list(base.glob(pattern))
            except Exception:  # noqa: BLE001
                hits = []
            if not hits:
                return False

        return True

    async def execute(self) -> list[FileUpdate]:
        base = kernel_data_dir
        all_data: list[dict[str, Any]] = []

        for guard in self.guards:
            pattern = guard.pattern
            for file_path in sorted(base.glob(pattern), key=lambda p: p.name):
                try:
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(data, dict):
                    all_data.append(data)
                # move to done
                done_dir = file_path.parent / "done"
                done_dir.mkdir(parents=True, exist_ok=True)
                move_to_done(file_path, done_dir)

        if not all_data:
            return []

        # 合并
        merged = all_data[0] if self._merge_mode == "first" else {"merged_sources": all_data}

        merge_id = next_record_id("merge")
        # 使用第一个 emit 路径
        emit_path = self.produces[0].path if self.produces else f"pipeline/merged/merge_{merge_id}.json"
        emit_path = emit_path.replace("*", merge_id)

        return [
            FileUpdate(
                descriptor=FileDescriptor(path=emit_path, schema="json"),
                content=merged,
            )
        ]
