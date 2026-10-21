"""调用方的容器修改不能改变世界事实、缓存和已提出的工具参数。"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from aurora_bot.ai.openai import to_openai_messages
from aurora_bot.contracts import (
    ChatMessage,
    EnvironmentEvent,
    ToolCall,
    ToolDefinition,
    WorldCommit,
    WorldCommitInput,
    WorldFrontier,
)
from aurora_bot.contracts.memory import MemoryRequest
from aurora_bot.mcp.models import McpInboundEvent
from aurora_bot.memory import Memory
from aurora_bot.memory_model.rules import RuleMemoryPolicy
from aurora_bot.utils import thaw_json
from aurora_bot.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 10, 18, tzinfo=UTC)


def test_world_and_inbound_values_detach_nested_caller_owned_containers() -> None:
    """所有输入阶段都复制嵌套内容，对原容器和结果容器的修改均不影响事实。"""
    payload: dict[str, Any] = {"items": [{"text": "原始事实", "labels": ["重要"]}]}
    frontier = WorldFrontier()
    event = EnvironmentEvent("event", "test", "test:world", "message", _NOW, "输入", payload)
    incoming = McpInboundEvent("event", "test:world", "message", _NOW, "输入", payload)
    proposed = WorldCommitInput("commit", "message", "test", "输入", frozenset({"test:world"}), frontier, payload)
    stored = WorldCommit("commit", "message", "test", "输入", _NOW, {"test:world": 1}, frontier, payload)
    payload["items"][0]["text"] = "外部改写"
    payload["items"][0]["labels"].append("后来添加")
    for frozen in (event.data, incoming.data, proposed.data, stored.data):
        assert frozen["items"][0]["text"] == "原始事实"
        assert frozen["items"][0]["labels"] == ("重要",)
        with pytest.raises(TypeError):
            frozen["items"][0]["text"] = "改写历史"


def test_tool_parameters_and_schema_stay_fixed_but_provider_uses_plain_json() -> None:
    """Provider 接收独立可序列化内容，无法通过共享容器改变原始调用。"""
    arguments: dict[str, Any] = {"items": [{"text": "原始参数"}]}
    schema: dict[str, Any] = {"type": "object", "properties": {"items": {"type": "array"}}}
    call = ToolCall("call", "test:tool/definition/echo", arguments)
    definition = ToolDefinition("test:tool/definition/echo", "回显", schema)
    arguments["items"][0]["text"] = "修改后参数"
    schema["properties"]["items"]["type"] = "string"
    assert definition.parameters["properties"]["items"]["type"] == "array"
    messages = to_openai_messages((ChatMessage.assistant(tool_calls=(call,)),))
    wire = json.loads(messages[0]["tool_calls"][0]["function"]["arguments"])
    assert wire == {"items": [{"text": "原始参数"}]}
    wire["items"][0]["text"] = "Provider 端修改"
    assert call.arguments["items"][0]["text"] == "原始参数"


def test_world_reopen_and_memory_cache_preserve_nested_facts_and_fingerprints(tmp_path: Path) -> None:
    """写入、读缓存和重启重读都使用不可变事实，JSON 展开只产生副本。"""

    async def scenario() -> None:
        path = tmp_path / "world.sqlite3"
        world = SqlAlchemyWorldJournal(path, now=lambda: _NOW)
        await world.initialize()
        try:
            data: dict[str, Any] = {"items": [{"value": "已经执行"}], "memory": {"entity_ids": ["operation-7"]}}
            proposal = WorldCommitInput(
                "fact", "tool.result", "test", "已有结果", frozenset({"test:world"}), WorldFrontier(), data
            )
            data["items"][0]["value"] = "错误改写"
            (commit,) = await world.append_commits((proposal,))
            assert commit.data["items"][0]["value"] == "已经执行"
            assert await world.append_commits((proposal,)) == (commit,)
            memory = Memory(world, policy=RuleMemoryPolicy())
            request = MemoryRequest(query="operation-7", cursor=commit.cursor, observed_at=_NOW)
            before = await memory.recall(request)
            mutable = thaw_json(commit.data)
            mutable["items"][0]["value"] = "副本修改"
            assert await memory.recall(request) == before
        finally:
            await world.close()
        reopened = SqlAlchemyWorldJournal(path)
        try:
            await reopened.initialize()
            restored = await reopened.commit("fact")
            assert restored is not None
            assert restored.data["items"][0]["value"] == "已经执行"
            assert await Memory(reopened, policy=RuleMemoryPolicy()).recall(request) == before
        finally:
            await reopened.close()

    asyncio.run(scenario())
