from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from aurora.output_delivery import deliver_reactive_output
from src.contracts import (
    MCP_EVENT_RECEIVED,
    OUTPUT_DELIVERY_REQUESTED,
    OUTPUT_DELIVERY_SUCCEEDED,
    OUTPUT_DELIVERY_UNKNOWN,
    AgentDefinition,
    AgentTree,
    ToolCall,
    ToolDefinition,
    ToolOutput,
    ToolStatus,
    WorldCommit,
    WorldCommitInput,
    WorldFrontier,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


class FakeWorld:
    def __init__(self, cause: WorldCommit, *, requested: bool = False) -> None:
        self.commits = {cause.commit_id: cause}
        self.inputs: list[WorldCommitInput] = []
        if requested:
            self.commits["tree:output:delivery:requested"] = WorldCommit(
                "tree:output:delivery:requested",
                OUTPUT_DELIVERY_REQUESTED,
                "output",
                "已有请求",
                datetime.now(UTC),
                {"aurora:tree:tree": 1},
                WorldFrontier(),
                {"tree_id": "tree"},
            )

    async def commit(self, commit_id: str) -> WorldCommit | None:
        return self.commits.get(commit_id)

    async def append_commit(
        self,
        *,
        commit_id: str,
        kind: str,
        source: str,
        summary: str,
        scopes: frozenset[str],
        based_on: WorldFrontier,
        data: Mapping[str, object],
        occurred_at: datetime | None = None,
    ) -> WorldCommit:
        item = WorldCommitInput(commit_id, kind, source, summary, scopes, based_on, data, occurred_at)
        self.inputs.append(item)
        commit = WorldCommit(
            commit_id,
            kind,
            source,
            summary,
            occurred_at or datetime.now(UTC),
            {scope: len(self.inputs) for scope in scopes},
            based_on,
            data,
        )
        self.commits[commit_id] = commit
        return commit


@dataclass(slots=True)
class FakeTool:
    name: str
    output: ToolOutput = field(default_factory=lambda: ToolOutput("发送成功"))
    calls: list[ToolCall] = field(default_factory=list)

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(self.name, "发送消息", {"type": "object"})

    async def execute(self, call: ToolCall) -> ToolOutput:
        self.calls.append(call)
        return self.output


@dataclass(frozen=True, slots=True)
class FakeMcp:
    tools: tuple[FakeTool, ...]


def _completed_tree(content: str = "在的，怎么啦？") -> AgentTree:
    definition = AgentDefinition("builtin.chat", "即时回复", "builtin.chat", "fast", frozenset(), frozenset())
    return AgentTree.create("tree", "root", definition, "在吗").complete("root", content)


def _cause(event_kind: str, data: Mapping[str, object], scope: str) -> WorldCommit:
    return WorldCommit(
        "mcp:org.aurora.qq:event:1",
        MCP_EVENT_RECEIVED,
        "mcp:org.aurora.qq",
        "收到 QQ 消息",
        datetime.now(UTC),
        {scope: 1, "aurora:mcp:org.aurora.qq": 2},
        WorldFrontier(),
        {"event_kind": event_kind, "data": dict(data)},
    )


def test_private_reactive_output_uses_frozen_qq_tool_and_records_delivery() -> None:
    cause = _cause("qq.message.private", {"user_id": "42", "message_id": "7"}, "qq:private:42")
    world = FakeWorld(cause)
    tool = FakeTool("aur.mcp.org.aurora.qq.qq_send_private_message")

    result = asyncio.run(deliver_reactive_output(world, FakeMcp((tool,)), _completed_tree(), cause.commit_id))

    assert result is not None and result["status"] == ToolStatus.SUCCEEDED.value
    assert len(tool.calls) == 1
    assert tool.calls[0].arguments == {"user_id": "42", "text": "在的，怎么啦？"}
    assert [item.kind for item in world.inputs] == [OUTPUT_DELIVERY_REQUESTED, OUTPUT_DELIVERY_SUCCEEDED]


def test_group_reactive_output_replies_to_original_message() -> None:
    cause = _cause("qq.message.group", {"group_id": "100", "message_id": "8"}, "qq:group:100")
    world = FakeWorld(cause)
    tool = FakeTool("aur.mcp.org.aurora.qq.qq_send_group_message")

    asyncio.run(deliver_reactive_output(world, FakeMcp((tool,)), _completed_tree("我在"), cause.commit_id))

    assert tool.calls[0].arguments == {"group_id": "100", "text": "我在", "reply_to": "8"}


def test_existing_delivery_request_is_marked_unknown_without_resending() -> None:
    cause = _cause("qq.message.private", {"user_id": "42"}, "qq:private:42")
    world = FakeWorld(cause, requested=True)
    tool = FakeTool("aur.mcp.org.aurora.qq.qq_send_private_message")

    result = asyncio.run(deliver_reactive_output(world, FakeMcp((tool,)), _completed_tree(), cause.commit_id))

    assert result is not None and result["status"] == ToolStatus.UNKNOWN.value
    assert tool.calls == []
    assert [item.kind for item in world.inputs] == [OUTPUT_DELIVERY_UNKNOWN]
