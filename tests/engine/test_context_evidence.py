"""主动读取和世界输入的来源随实际保留的消息进入审计。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from aurora_bot.ai.openai import to_openai_messages
from aurora_bot.contracts import AgentDefinition, ChatMessage, CognitionRequest, ToolCall, ToolScopes, WorldFrontier
from aurora_bot.contracts.memory_codec import read_exposure
from aurora_bot.contracts.operation import OperationDefinition, OperationRequest, OperationResult
from aurora_bot.contracts.resource import ResourceKey, ResourceRef
from aurora_bot.operations.registry import OperationRegistry
from aurora_bot.operations.tool import operation_tools
from aurora_bot.resources.catalog import ResourceCatalog
from aurora_bot.world import SqlAlchemyWorldJournal
from tests.support.engine import make_engine
from tests.support.model import ScriptedModel as FakeModel
from tests.support.prompt import _agent, _assembler

if TYPE_CHECKING:
    from pathlib import Path


def test_trimmed_tool_evidence_is_not_counted_and_literal_mentions_do_not_create_sources() -> None:
    """旧工具组退出后，其来源也退出曝光；最新正文提到旧 ID 不改变这一点。"""
    transcript = (
        ChatMessage.message("核对"),
        ChatMessage.assistant(tool_calls=(ToolCall("old-call", "read", {}),)),
        ChatMessage.tool("old-call", "原始记录", evidence_refs=("old-source",)),
        ChatMessage.message("很长的讨论" * 500),
        ChatMessage.assistant(tool_calls=(ToolCall("current-call", "read", {}),)),
        ChatMessage.tool("current-call", "提到 old-source 的新结果", evidence_refs=("current-source",)),
    )
    trimmed = _assembler(limit=500).assemble(_agent().prompt_id, transcript)
    assert trimmed.memory is not None
    assert trimmed.memory.transcript_ids == ("current-source",)
    assert trimmed.memory.included_ids == ("current-source",)
    complete = _assembler(limit=10_000).assemble(_agent().prompt_id, transcript)
    assert complete.memory is not None
    assert complete.memory.transcript_ids == ("old-source", "current-source")
    with pytest.raises(ValueError, match="只有世界输入和工具结果"):
        ChatMessage("assistant", "模型自己声称来源", evidence_refs=("fabricated",))


class EvidenceOperation:
    """环境能力返回结构化来源，而不是让模型从正文创建来源。"""

    @property
    def definition(self) -> OperationDefinition:
        """公开同一资源定义供路由及工具投影使用。"""
        return OperationDefinition(
            ResourceRef(ResourceKey.parse("test:records/query/read"), "1"),
            "读取原始证据",
            {"type": "object", "properties": {}, "additionalProperties": False},
            "test:tool/definition/read",
            True,
        )

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """本例只读已经明确寻址的来源。"""
        return ToolScopes()

    async def execute(self, request: OperationRequest) -> OperationResult:
        """明确指出本次返回了哪个世界记录的内容。"""
        return OperationResult({"summary": "实验已经发起"}, evidence_refs=("source",))


def test_operation_sources_survive_receipt_tool_projection_engine_and_provider_boundary(tmp_path: Path) -> None:
    """来源经过统一路由和工具返回进入实际模型审计，内部元数据不会成为 Provider 协议字段。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        try:
            await world.initialize()
            await world.append_commit(
                commit_id="source",
                kind="experiment.started",
                source="test",
                summary="实验已经发起",
                scopes=frozenset({"test:world/experiment"}),
                based_on=WorldFrontier(),
                data={},
            )
            operation = EvidenceOperation()
            catalog = ResourceCatalog((operation.definition.resource,))
            registry = OperationRegistry("aurora:bot/test", (operation,), catalog, world)
            tools = operation_tools(registry, "aurora:bot/test")
            definition = _agent()
            agent = AgentDefinition(
                definition.definition_id,
                definition.description,
                definition.prompt_id,
                definition.model,
                frozenset({"test:tool/definition/read"}),
            )
            model = FakeModel(
                [
                    ChatMessage.assistant(tool_calls=(ToolCall("read", "test:tool/definition/read", {}),)),
                    ChatMessage.assistant("已核对"),
                ]
            )
            engine = make_engine(model, (agent,), tools=tools, world=world, bot_id="aurora:bot/test")
            await engine.execute(CognitionRequest("读取证据", agent=agent.definition_id, run_id="run"))
            event = await world.commit("run:model:1:requested")
            assert event is not None
            exposure = read_exposure(event.data["memory"])
            assert exposure.included_ids == ("source",)
            result = await world.commit("run:tool:read:result")
            assert result is not None and result.data["evidence_refs"] == ("source",)
            assert model.requests[-1].messages[-1].evidence_refs == ("source",)
            assert all("evidence_refs" not in message for message in to_openai_messages(model.requests[-1].messages))
        finally:
            await world.close()

    asyncio.run(scenario())
