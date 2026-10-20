"""可读记忆内容和显式关系的世界记录投影。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from aurorabot.utils import thaw_json

if TYPE_CHECKING:
    from aurorabot.contracts.world import WorldCommit


def memory_text(commit: WorldCommit) -> str:
    """保留可读内容和完整结构化事实，用作基线特征及容量估算。"""
    return f"{commit.summary}\n{json.dumps(thaw_json(commit.data), ensure_ascii=False, separators=(',', ':'))}"


def memory_links(commit: WorldCommit, name: str) -> tuple[str, ...]:
    """只读取显式关系元数据，格式错误的外部内容不产生图关系。"""
    metadata = commit.data.get("memory")
    links = _strings(metadata, name) if isinstance(metadata, Mapping) else ()
    if name == "goal_ids":
        direct = commit.data.get("goal_id")
        links += (direct,) if isinstance(direct, str) and direct.strip() else ()
        links += _strings(commit.data, "focus_goal_ids")
    return tuple(dict.fromkeys(links))


def _strings(data: Mapping[str, Any], name: str) -> tuple[str, ...]:
    """接受显式字符串集合，不把任意嵌套文本当成结构化关系。"""
    values = data.get(name, ())
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        return ()
    return tuple(values)
