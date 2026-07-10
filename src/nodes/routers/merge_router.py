"""MergeRouter — 多源汇聚路由。

按 config.strategy ("all"/"any") 等待条件满足后触发。
"""

from __future__ import annotations

import json
from typing import Any

from src.kernel.base import FileDescriptor, FileEvent, FileUpdate, NodeState, Router
from src.kernel.state_store import kernel_data_dir, move_to_done, next_record_id
from src.utils.log_utils import get_logger

logger = get_logger("MergeRouter")


class MergeRouter(Router):
    """多源汇聚路由。"""

    _default_guards: list[str] = []
    _default_produces: list[str] = []

    def __init__(
        self,
        node_id: str,
        *,
        strategy: str = "all",
        match_by: str | None = None,
        merge_mode: str = "concat",
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, **kwargs)
        self._strategy = strategy
        self._match_by = match_by
        self._merge_mode = merge_mode
        self._source_files: dict[str, list[str]] = {}

    def on_event(self, event: FileEvent) -> bool:
        if self.state not in (NodeState.IDLE, NodeState.READY):
            return False
        matched_guard = None
        for i, guard in enumerate(self.guards):
            if guard.match(event.path):
                matched_guard = i
                break
        if matched_guard is None:
            return False
        if self._strategy == "any":
            return True
        # "all" strategy: 检查所有源都有文件
        base = kernel_data_dir
        for guard in self.guards:
            pattern = guard.pattern
            try:
                hits = list(base.glob(pattern))
            except Exception:
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
                done_dir = file_path.parent / "done"
                done_dir.mkdir(parents=True, exist_ok=True)
                move_to_done(file_path, done_dir)

        if not all_data:
            return []

        merged = all_data[0] if self._merge_mode == "first" else {"merged_sources": all_data}

        merge_id = next_record_id("merge")
        emit_path = self.produces[0].path if self.produces else f"pipeline/merged/merge_{merge_id}.json"
        emit_path = emit_path.replace("*", merge_id)

        return [
            FileUpdate(
                descriptor=FileDescriptor(path=emit_path, schema="json"),
                content=merged,
            )
        ]
