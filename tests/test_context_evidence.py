"""主动读取和世界输入的来源随实际保留的消息进入审计。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from test_engine_runtime import FakeModel
from test_prompt import _agent, _assembler

from src.agents import AgentCatalog
from src.ai.openai import to_openai_messages
from src.contracts import AgentDefinition, AgentTree, ChatMessage, ToolCall, ToolScopes, WorldFrontier
from src.contracts.memory_codec import read_exposure
from src.contracts.operation import OperationDefinition, OperationRequest, OperationResult
from src.contracts.resource import ResourceKey, ResourceRef
from src.engine import AgentTreeRunner
from src.operations.registry import OperationRegistry
from src.operations.tool import operation_tools
from src.resources.catalog import ResourceCatalog
from src.tools import ToolRegistry
from src.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path


def test_trimmed_tool_evidence_is_not_counted_and_literal_mentions_do_not_create_sources() -> None:
    """旧工具组退出后，其来源也退出曝光；最新正文提到旧 ID 不改变这一点。"""
    tree = AgentTree.create("tree", "root", _agent(), "核对")
    tree = tree.append("root", ChatMessage.assistant(tool_calls=(ToolCall("old-call", "read", {}),)))
    tree = tree.append("root", ChatMessage.tool("old-call", "原始记录", evidence_refs=("old-source",)))
    tree = tree.append("root", ChatMessage.message("很长的讨论" * 500))
    tree = tree.append("root", ChatMessage.assistant(tool_calls=(ToolCall("current-call", "read", {}),)))
    tree = tree.append(
        "root", ChatMessage.tool("current-call", "提到 old-source 的新结果", evidence_refs=("current-source",))
    )
    trimmed = _assembler(limit=500).assemble(tree, "root")
    assert trimmed.memory is not None
    assert trimmed.memory.transcript_ids == ("current-source",)
    assert trimmed.memory.included_ids == ("current-source",)
    complete = _assembler(limit=10_000).assemble(tree, "root")
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
            "test:tool/read",
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
            tools = ToolRegistry(operation_tools(registry, "aurora:bot/test"))
            definition = _agent()
            agent = AgentDefinition(
                definition.definition_id,
                definition.description,
                definition.prompt_id,
                definition.model,
                frozenset({"test:tool/read"}),
                frozenset(),
            )
            model = FakeModel(
                [
                    ChatMessage.assistant(tool_calls=(ToolCall("read", "test:tool/read", {}),)),
                    ChatMessage.assistant("已核对"),
                ]
            )
            tree = AgentTree.create("tree", "root", agent, "读取证据")
            await AgentTreeRunner(
                model,
                _assembler(),
                AgentCatalog((agent,)),
                tools,
                world=world,
                bot_id="aurora:bot/test",
            ).run(tree)
            event = await world.commit("tree:root:model:1:requested")
            assert event is not None
            exposure = read_exposure(event.data["memory"])
            assert exposure.included_ids == ("source",)
            result = await world.commit("tree:root:read:result")
            assert result is not None and result.data["evidence_refs"] == ("source",)
            assert model.requests[-1].messages[-1].evidence_refs == ("source",)
            assert all("evidence_refs" not in message for message in to_openai_messages(model.requests[-1].messages))
        finally:
            await world.close()

    asyncio.run(scenario())
