"""Bot 可以主动召回及展开来源，工具返回的证据参与实际曝光审计。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from memory_operations_support import GOAL, SOURCE, prepared_runtime, request
from test_assembly import FakeModel

from aurora import load_config
from aurorabot.contracts import ChatMessage, ModelRequest, ToolCall, TreeLaunchRequest, WorldFrontier
from aurorabot.contracts.memory_codec import read_exposure
from aurorabot.contracts.operation import OperationStatus
from aurorabot.contracts.pkgs.operations import OperationRegistry
from aurorabot.runtime import assemble_runtime

if TYPE_CHECKING:
    from pathlib import Path


def test_source_query_honors_knowledge_boundary_and_discloses_known_revisions(configured_project: Path) -> None:
    """知道来源 ID 不能绕过历史可见性，后来的修订也不会进入过去。"""

    async def scenario() -> None:
        async with prepared_runtime(configured_project) as (runtime, _model_id):
            registry = runtime.assembly.get(OperationRegistry)
            cutoff = await runtime.world.cursor()
            await runtime.world.append_commit(
                commit_id="revised",
                kind="experiment.updated",
                source="test",
                summary="已确认结果需要复核",
                scopes=frozenset({"test:world/experiment"}),
                based_on=WorldFrontier(),
                data={"memory": {"supersedes": [SOURCE]}, "repeat_allowed": False},
            )
            current = await registry.dispatch(request(runtime, "current", "query/source", {"memory_id": SOURCE}))
            assert current.data["superseded_by"] == ("revised",)
            historical = await registry.dispatch(
                request(runtime, "history", "query/source", {"memory_id": SOURCE, "cursor": cutoff})
            )
            assert historical.data["superseded_by"] == ()
            unavailable = await registry.dispatch(
                request(runtime, "not-known", "query/source", {"memory_id": "revised", "cursor": cutoff})
            )
            assert unavailable.status is OperationStatus.FAILED
            recalled = await registry.dispatch(
                request(runtime, "recall", "query/recall", {"query": "核对实验", "focus_goal_ids": [GOAL]})
            )
            assert recalled.status is OperationStatus.SUCCEEDED
            assert SOURCE in recalled.evidence_refs and "revised" in recalled.evidence_refs
            assert all("summary_complete" in item for item in recalled.data["required"])

    asyncio.run(scenario())


class ReadingModel(FakeModel):
    """在自动召回范围之外主动展开一项来源。"""

    async def complete(self, request: ModelRequest) -> ChatMessage:
        """使用实际注册的记忆工具并随后结束认知。"""
        self.requests.append(request)
        if len(self.requests) == 1:
            return ChatMessage.assistant(
                tool_calls=(ToolCall("source", "aurora:tool/definition/memory_source", {"memory_id": "tool-only"}),)
            )
        return ChatMessage.assistant("我已经读取补充来源。")


def test_bot_can_expand_a_source_and_audit_only_the_subsequent_actual_exposure(configured_project: Path) -> None:
    """来源不在自动推荐中，显式工具读取后才进入下一次模型请求的曝光。"""

    async def scenario() -> None:
        async with prepared_runtime(configured_project) as (prepared, _model_id):
            await prepared.world.append_commit(
                commit_id="tool-only",
                kind="experiment.note",
                source="test",
                summary="补充来源",
                scopes=frozenset({"test:world/extra"}),
                based_on=WorldFrontier(),
                data={"detail": "可以继续核对"},
            )
        model = ReadingModel()
        runtime = assemble_runtime(load_config(configured_project), model, output=lambda _: None)
        try:
            await runtime.launch_tree(
                TreeLaunchRequest("读取补充来源", tree_id="source-read", memory_scopes=frozenset())
            )
            first = await runtime.world.commit("source-read:root:model:0:requested")
            second = await runtime.world.commit("source-read:root:model:1:requested")
            assert first is not None and second is not None
            assert read_exposure(first.data["memory"]).included_ids == ()
            exposure = read_exposure(second.data["memory"])
            assert exposure.included_ids == ("tool-only",)
            assert exposure.transcript_ids == ("tool-only",)
            assert exposure.recall is not None and exposure.recall.ranking == ()
            assert "可以继续核对" in model.requests[-1].messages[-1].content
        finally:
            await runtime.world.close()

    asyncio.run(scenario())
