"""终态 Task JSON 的压缩投影与只读回查。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.utils.serialization import read_json

if TYPE_CHECKING:
    from pathlib import Path

TASK_ARCHIVE_VERSION = 2


def task_archive_projection(detail: dict[str, Any]) -> dict[str, Any]:
    """移除只服务于活跃恢复的重放数据，并压缩重复 Tool schema。"""

    def project(value: Any) -> Any:
        if isinstance(value, dict):
            projected = {key: project(item) for key, item in value.items() if key not in {"continuation", "tools"}}
            tools = value.get("tools")
            if isinstance(tools, (list, tuple)) and all(
                isinstance(item, dict) and isinstance(item.get("name"), str) for item in tools
            ):
                projected["tool_names"] = [item["name"] for item in tools]
            return projected
        if isinstance(value, (list, tuple)):
            return [project(item) for item in value]
        return value

    projected = project(detail)
    assert isinstance(projected, dict)
    return {"archive_version": TASK_ARCHIVE_VERSION, **projected}


def read_task_archive(path: Path, task_id: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = read_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    task = value.get("task")
    if not isinstance(task, dict) or task.get("task_id") != task_id:
        return None
    return value


def archived_agent_detail(directory: Path, agent_id: str) -> dict[str, Any] | None:
    """从 Task 归档中回查已离开热库的 Agent。"""
    for archive in directory.glob("*.json"):
        try:
            value = read_json(archive)
        except (OSError, ValueError):
            continue
        if not isinstance(value, dict) or not isinstance(value.get("agents"), list):
            continue
        agents = [item for item in value["agents"] if isinstance(item, dict)]
        agent = next((item for item in agents if item.get("agent_id") == agent_id), None)
        if agent is None:
            continue
        return {
            "agent": agent,
            "children": [item for item in agents if item.get("parent_agent_id") == agent_id],
            "messages": (),
            "archive_version": value.get("archive_version", 1),
        }
    return None
