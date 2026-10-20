"""记忆审计只记录实际装配来源，不从消息正文猜测曝光。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from test_engine_runtime import FakeModel
from test_memory_selection import _NOW, _fact
from test_prompt import _agent, _assembler

from aurorabot.agents import AgentCatalog
from aurorabot.contracts import AgentTree, ChatMessage, MemoryScopeSnapshot, MemorySnapshot
from aurorabot.contracts.memory import MemoryBundle, MemoryRecall, MemoryRequest, MemoryScore
from aurorabot.contracts.memory_codec import exposure_data, read_exposure
from aurorabot.contracts.resource import ResourceKey, ResourceRef
from aurorabot.engine import AgentTreeRunner
from aurorabot.tools import ToolRegistry
from aurorabot.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path


def _snapshot() -> MemorySnapshot:
    """同时提供必要证据、超预算推荐和可以载入的小集合。"""
    support = _fact("support", "行动已经发起", 1)
    large = _fact("large", "无关细节" * 1000, 2)
    small = _fact("small", "需要检查 large 中提到的状态", 3)
    recall = MemoryRecall(
        MemoryRequest(query="检查状态", scopes=frozenset({"test:world/facts"}), cursor=3, observed_at=_NOW),
        _policy_ref(),
        _NOW,
        50,
        (MemoryScore("large", 2.0), MemoryScore("small", 1.0)),
        {"similarity": 4},
    )
    return MemorySnapshot(
        _NOW,
        (),
        bundles=(MemoryBundle((large,), 2.0), MemoryBundle((support, small), 1.0)),
        required=(support,),
        missing_refs=("absent",),
        recall=recall,
    )


def _policy_ref() -> ResourceRef:
    """使用一个确定的公开模型版本。"""
    return ResourceRef(ResourceKey.parse("aurora:memory/model/rules"), "1")


def test_budgeted_assembly_reports_actual_evidence_and_recall_roundtrips() -> None:
    """推荐过但未载入的内容、正文提及的 ID 都不能成为曝光。"""
    snapshot = _snapshot()
    tree = AgentTree.create("tree", "root", _agent(), "继续核对 large 和 absent。")
    assembled = _assembler(limit=900).assemble(tree, "root", memory=snapshot)
    assert assembled.memory is not None
    assert assembled.memory.recommended_ids == ("large", "support", "small")
    assert assembled.memory.included_ids == ("support", "small")
    assert assembled.memory.required_ids == ("support",)
    assert assembled.memory.missing_refs == ("absent",)
    assert "large" in assembled.messages[0].content
    assert "无关细节" not in assembled.messages[0].content
    assert read_exposure(exposure_data(assembled.memory)) == assembled.memory


def test_scope_sources_are_deduplicated_and_required_sources_are_not_repeated() -> None:
    """同一经历出现在多个域或必要证据中时，正文及曝光身份都只载入一次。"""
    commit = _fact("shared", "共享经历", 1)
    snapshot = MemorySnapshot(
        _NOW, (MemoryScopeSnapshot("first", 1, (commit,)), MemoryScopeSnapshot("second", 1, (commit,)))
    )
    tree = AgentTree.create("tree", "root", _agent(), "核对")
    assembled = _assembler().assemble(tree, "root", memory=snapshot)
    assert assembled.messages[0].content.count("共享经历") == 1
    assert assembled.memory is not None and assembled.memory.included_ids == ("shared",)
    required = _assembler().assemble(tree, "root", memory=replace(snapshot, required=(commit,)))
    assert required.messages[0].content.count("共享经历") == 1
    assert required.memory is not None and required.memory.included_ids == ("shared",)


def test_engine_persists_the_assembled_exposure_before_model_attempt(tmp_path: Path) -> None:
    """模型调用事件持久保存真实装配结果，重启读取不需要重新运行推荐器。"""
    snapshot = _snapshot()

    class FixedMemory:
        """让引擎与组装器使用同一份可复查输入。"""

        async def recall(self, request: MemoryRequest | None = None) -> MemorySnapshot:
            """固定证据来源，不访问外部环境。"""
            return snapshot

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        agent = _agent()
        tree = AgentTree.create("tree", "root", agent, "核对")
        model = FakeModel([ChatMessage.assistant("已核对")])
        try:
            await AgentTreeRunner(
                model,
                _assembler(limit=900),
                AgentCatalog((agent,)),
                ToolRegistry(()),
                world=world,
                memory=FixedMemory(),
            ).run(tree)
            event = await world.commit("tree:root:model:0:requested")
            assert event is not None
            exposure = read_exposure(event.data["memory"])
            assert exposure.included_ids == ("support", "small")
            assert exposure.recall == snapshot.recall
            assert "无关细节" not in model.requests[0].messages[0].content
        finally:
            await world.close()

    asyncio.run(scenario())
