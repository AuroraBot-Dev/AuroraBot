"""把 reactive AgentTree 的最终文本可靠投递回原 MCP 会话。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from src.contracts import (
    OUTPUT_DELIVERY_FAILED,
    OUTPUT_DELIVERY_REQUESTED,
    OUTPUT_DELIVERY_SUCCEEDED,
    OUTPUT_DELIVERY_UNKNOWN,
    Tool,
    ToolCall,
    ToolOutput,
    ToolStatus,
    WorldFrontier,
    tree_scope,
)

if TYPE_CHECKING:
    from datetime import datetime

    from src.contracts import AgentTree, WorldCommit

_QQ_SOURCE = "mcp:org.aurora.qq"
_QQ_PRIVATE_KIND = "qq.message.private"
_QQ_GROUP_KIND = "qq.message.group"
_QQ_PRIVATE_TOOL = "aur.mcp.org.aurora.qq.qq_send_private_message"
_QQ_GROUP_TOOL = "aur.mcp.org.aurora.qq.qq_send_group_message"


@dataclass(frozen=True, slots=True)
class _DeliveryRoute:
    tool_id: str
    arguments: Mapping[str, Any]


class _DeliveryWorld(Protocol):
    async def commit(self, commit_id: str) -> WorldCommit | None: ...

    async def append_commit(
        self,
        *,
        commit_id: str,
        kind: str,
        source: str,
        summary: str,
        scopes: frozenset[str],
        based_on: WorldFrontier,
        data: Mapping[str, Any],
        occurred_at: datetime | None = None,
    ) -> WorldCommit: ...


class _DeliveryTools(Protocol):
    @property
    def tools(self) -> tuple[Tool, ...]: ...


async def deliver_reactive_output(
    world: _DeliveryWorld,
    mcp: _DeliveryTools,
    tree: AgentTree,
    caused_by: str,
) -> dict[str, object] | None:
    """按原提交选择冻结 Tool；已有请求没有结果时保守标记 unknown，不重复外部效果。"""
    commit = await world.commit(caused_by)
    if commit is None:
        return {"status": ToolStatus.FAILED.value, "error": "找不到触发回复的世界提交"}
    content = tree.node(tree.root_id).result
    if content is None or not content.strip():
        return {"status": ToolStatus.FAILED.value, "error": "AgentTree 没有可投递的最终文本"}
    route = _route(commit, content)
    if route is None:
        return None

    prefix = f"{tree.tree_id}:output:delivery"
    requested_id = f"{prefix}:requested"
    result_id = f"{prefix}:result"
    existing = await world.commit(result_id)
    if existing is not None:
        return _result_view(existing.data)

    scopes = frozenset({tree_scope(tree.tree_id), *commit.scopes})
    requested = await world.commit(requested_id)
    if requested is not None:
        output = ToolOutput("投递请求已有记录但缺少确定结果，禁止自动重试", ToolStatus.UNKNOWN)
    else:
        await world.append_commit(
            commit_id=requested_id,
            kind=OUTPUT_DELIVERY_REQUESTED,
            source="output",
            summary="请求投递 AgentTree 回复",
            scopes=scopes,
            based_on=WorldFrontier(commit.scopes),
            data={"tree_id": tree.tree_id, "caused_by": caused_by, "tool": route.tool_id},
        )
        tool = next((candidate for candidate in mcp.tools if candidate.definition.name == route.tool_id), None)
        if tool is None:
            output = ToolOutput(f"回复投递工具不可用：{route.tool_id}", ToolStatus.FAILED)
        else:
            result = await tool.execute(ToolCall(f"delivery:{tree.tree_id}", route.tool_id, route.arguments))
            output = (
                result
                if isinstance(result, ToolOutput)
                else ToolOutput("回复投递工具返回了非法结果", ToolStatus.FAILED)
            )

    kind = {
        ToolStatus.SUCCEEDED: OUTPUT_DELIVERY_SUCCEEDED,
        ToolStatus.FAILED: OUTPUT_DELIVERY_FAILED,
        ToolStatus.UNKNOWN: OUTPUT_DELIVERY_UNKNOWN,
    }[output.status]
    await world.append_commit(
        commit_id=result_id,
        kind=kind,
        source="output",
        summary=f"AgentTree 回复投递{_status_label(output.status)}",
        scopes=scopes,
        based_on=WorldFrontier(commit.scopes),
        data={
            "tree_id": tree.tree_id,
            "caused_by": caused_by,
            "tool": route.tool_id,
            "status": output.status.value,
            "detail": output.content,
        },
    )
    return {"status": output.status.value, "tool": route.tool_id, "detail": output.content}


def _route(commit: WorldCommit, content: str) -> _DeliveryRoute | None:
    if commit.source != _QQ_SOURCE or commit.data.get("event_kind") not in {_QQ_PRIVATE_KIND, _QQ_GROUP_KIND}:
        return None
    data = commit.data.get("data")
    if not isinstance(data, Mapping):
        return None
    if commit.data["event_kind"] == _QQ_PRIVATE_KIND:
        user_id = _identifier(data.get("user_id"))
        return _DeliveryRoute(_QQ_PRIVATE_TOOL, {"user_id": user_id, "text": content}) if user_id else None
    group_id = _identifier(data.get("group_id"))
    if group_id is None:
        return None
    arguments: dict[str, Any] = {"group_id": group_id, "text": content}
    message_id = _identifier(data.get("message_id"))
    if message_id is not None:
        arguments["reply_to"] = message_id
    return _DeliveryRoute(_QQ_GROUP_TOOL, arguments)


def _identifier(value: object) -> str | None:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        text = str(value).strip()
        return text or None
    return None


def _status_label(status: ToolStatus) -> str:
    return {
        ToolStatus.SUCCEEDED: "成功",
        ToolStatus.FAILED: "失败",
        ToolStatus.UNKNOWN: "结果未知",
    }[status]


def _result_view(data: Mapping[str, object]) -> dict[str, object]:
    return {
        "status": data.get("status", ToolStatus.UNKNOWN.value),
        "tool": data.get("tool", ""),
        "detail": data.get("detail", ""),
    }


__all__ = ["deliver_reactive_output"]
