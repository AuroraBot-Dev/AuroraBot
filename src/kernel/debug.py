"""只读投影，供调试 API 和终止 Task 归档使用。

提供 Task/Agent 详情组装、旧版工作区检测与拒绝等功能。
所有函数均为纯投影，不产生副作用。
"""

from pathlib import Path
from typing import Any, Protocol


class DebugStore(Protocol):
    """调试存储接口协议，定义只读查询签名。"""

    def get_task(self, task_id: str) -> Any: ...
    def get_agent(self, agent_id: str) -> Any: ...
    def agents(self) -> tuple[Any, ...]: ...
    def children(self, agent_id: str) -> tuple[Any, ...]: ...
    def events_for_task(self, task_id: str) -> tuple[dict[str, Any], ...]: ...
    def messages_for_agent(self, agent_id: str) -> tuple[dict[str, Any], ...]: ...


def reject_active_legacy_workspace(process_directory: Path) -> None:
    """检测并拒绝旧版 Episode/Graph 工作区中有残留数据的情况。

    如果 process_directory 中存在 records 或 episodes 子目录且含有 JSON 文件，
    则抛出 RuntimeError，要求使用干净的工作区。
    """
    legacy = []
    for name in ("records", "episodes"):
        directory = process_directory / name
        if directory.exists() and any(directory.rglob("*.json")):
            legacy.append(str(directory))
    if legacy:
        raise RuntimeError(
            "legacy Episode/Graph workspace contains active data; "
            "select a clean runtime.workspace before starting: " + ", ".join(legacy)
        )


def task_detail(store: DebugStore, task_id: str) -> dict[str, Any] | None:
    task = store.get_task(task_id)
    if task is None:
        return None
    agents = [agent.to_dict() for agent in store.agents() if agent.task_id == task_id]
    nodes = {item["agent_id"]: {**item, "children": []} for item in agents}
    roots = []
    for item in nodes.values():
        parent_id = item["parent_agent_id"]
        if parent_id is None or parent_id not in nodes:
            roots.append(item)
        else:
            nodes[parent_id]["children"].append(item)
    events = store.events_for_task(task_id)
    return {
        "task": task.to_dict(),
        "budget": {
            "model_calls": task.model_calls,
            "max_model_calls": task.max_model_calls,
            "tool_calls": task.tool_calls,
            "max_tool_calls": task.max_tool_calls,
            "max_duration_seconds": task.max_duration_seconds,
        },
        "supervision_tree": roots,
        "agents": agents,
        "causal_summary": tuple(
            {
                "event_id": event["event_id"],
                "agent_id": event["agent_id"],
                "type": event["type"],
                "summary": event["summary"],
                "causation_id": event["causation_id"],
                "created_at": event["created_at"],
            }
            for event in events
        ),
        "events": events,
    }


def agent_detail(store: DebugStore, agent_id: str) -> dict[str, Any] | None:
    agent = store.get_agent(agent_id)
    if agent is None:
        return None
    messages = store.messages_for_agent(agent_id)
    return {
        "agent": agent.to_dict(),
        "children": [item.to_dict() for item in store.children(agent_id)],
        "messages": tuple(
            {
                "message_id": message["message_id"],
                "task_id": message["task_id"],
                "type": message["type"],
                "payload_keys": sorted(message["payload"]),
                "causation_id": message["causation_id"],
                "correlation_id": message["correlation_id"],
                "priority": message["priority"],
                "status": message["status"],
                "created_at": message["created_at"],
            }
            for message in messages
        ),
    }
