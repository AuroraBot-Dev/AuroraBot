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

logger = get_logger("MergeRouter")

_DATA_DIR = Config.KERNEL_DATA_DIR


class MergeRouter(Router):
    """多输入汇合 Router —— 等待所有上游文件就位后合并输出。

    纯机械逻辑，零 LLM 调用。

    守护一组文件模式。任一匹配文件变更时唤醒，
    ``execute()`` 中检查所有输入文件是否都存在：
    - 全部就位 → 读取、合并、写入输出文件
    - 未全部就位 → 返回空，回到 IDLE 等待下次事件

    参数在构造时通过 ``**config`` 传入：
    - ``input_patterns``: 输入文件 glob 列表，如 ``["actions/action_*.json"]``
    - ``output_path``: 合并输出文件路径
    - ``merge_strategy``: ``"concat_array"`` 或 ``"shallow_merge"``
    """

    def __init__(self, node_id: str, **config: Any) -> None:
        super().__init__(node_id)
        self._input_patterns: list[str] = [
            str(p) for p in config.get("input_patterns", ["actions/action_*.json"])
        ]
        self._output_path = str(config.get("output_path", "router/merge/merged.json"))
        self._merge_strategy = str(config.get("merge_strategy", "concat_array"))

    @property
    def type(self) -> str:
        return "router"

    @property
    def guards(self) -> list[FilePattern]:
        if self._config_watch is not None:
            return [FilePattern(p) for p in self._config_watch]
        return [FilePattern(p) for p in self._input_patterns]

    @property
    def produces(self) -> list[FileDescriptor]:
        if self._config_emit is not None:
            return [FileDescriptor(p) for p in self._config_emit]
        return [FileDescriptor(self._output_path)]

    async def execute(self) -> list[FileUpdate]:
        """检查所有输入文件是否存在，全部就位则合并输出。"""
        all_files: list[Path] = []
        for pattern in self._input_patterns:
            guard_path = _DATA_DIR / pattern
            parent = guard_path.parent
            pattern_name = guard_path.name

            if not parent.exists():
                return []  # 目录还不存在 → 未就位

            matched = sorted(parent.glob(pattern_name))
            if not matched:
                return []  # 某组输入无文件 → 未就位

            all_files.extend(matched)

        if not all_files:
            return []

        # 去重（同一文件可能匹配多个 pattern）
        seen: set[str] = set()
        unique: list[Path] = []
        for f in all_files:
            key = str(f.relative_to(_DATA_DIR))
            if key not in seen:
                seen.add(key)
                unique.append(f)

        # 读取并合并
        merged = self._merge_files(unique)
        if merged is None:
            return []

        logger.info(f"MergeRouter: 合并 {len(unique)} 个文件 → {self._output_path}")

        return [
            FileUpdate(
                descriptor=FileDescriptor(
                    path=self._output_path,
                    schema="json",
                ),
                content=merged,
            )
        ]

    def _merge_files(self, files: list[Path]) -> Any:
        if self._merge_strategy == "concat_array":
            result: list[Any] = []
            for f in files:
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        result.extend(data)
                    else:
                        result.append(data)
                except (OSError, json.JSONDecodeError) as exc:
                    logger.warning(f"MergeRouter 读取文件失败 {f}: {exc}")
                    continue
            return result

        # shallow_merge: 顶层字段合并（后者覆盖前者）
        merged_dict: dict[str, Any] = {}
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    merged_dict.update(data)
                else:
                    merged_dict[str(f.relative_to(_DATA_DIR))] = data
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(f"MergeRouter 读取文件失败 {f}: {exc}")
                continue
        return merged_dict

    def on_complete(self) -> None:
        if self.state != NodeState.ERROR:
            self.state = NodeState.IDLE
