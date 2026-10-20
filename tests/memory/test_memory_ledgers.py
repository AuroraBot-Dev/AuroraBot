"""运行台账不循环成为记忆候选，Bot 明确引用的必要证据仍可恢复。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from aurorabot.contracts import ScopeCatalog, ScopeKind, TreeLaunchRequest
from aurorabot.contracts.bot import BotChange, Checkpoint
from aurorabot.contracts.memory import MemoryRequest
from aurorabot.contracts.memory_graph_codec import read_ranking
from aurorabot.contracts.operation import OperationStatus
from aurorabot.contracts.pkgs.bot import BotStateStore
from aurorabot.contracts.pkgs.memory import MemoryReader
from aurorabot.contracts.pkgs.operations import OperationRegistry
from tests.memory.operations_support import GOAL, SOURCE, prepared_runtime, request

if TYPE_CHECKING:
    from pathlib import Path


def test_repeated_training_exports_do_not_feed_graph_payloads_back_into_memory(configured_project: Path) -> None:
    """导出与再运行交替进行时，图输入只保留真实业务经历。"""

    async def scenario() -> None:
        async with prepared_runtime(configured_project) as (runtime, original_model_id):
            registry = runtime.assembly.get(OperationRegistry)
            state = runtime.assembly.get(BotStateStore)
            ledger_scope = f"{state.scope}/operations"
            assert runtime.assembly.get(ScopeCatalog).classify(ledger_scope) is ScopeKind.RUN
            original = await registry.dispatch(
                request(runtime, "first-export", "query/training_input", {"model_request_id": original_model_id})
            )
            assert original.status is OperationStatus.SUCCEEDED
            graphs = []
            for index in range(2):
                tree = await runtime.launch_tree(
                    TreeLaunchRequest(
                        "继续核对实验",
                        tree_id=f"after-export-{index}",
                        focus_goal_ids=(GOAL,),
                    )
                )
                model_id = f"{tree.tree_id}:{tree.root_id}:model:0:requested"
                result = await registry.dispatch(
                    request(runtime, f"export-{index}", "query/training_input", {"model_request_id": model_id})
                )
                assert result.status is OperationStatus.SUCCEEDED
                rebuilt = read_ranking(result.data["request"])
                assert all(not item.memory_id.startswith("operation:") for item in rebuilt.candidates)
                assert all(
                    not event.source.identity.startswith("operation:")
                    for event in rebuilt.interactions
                    if event.source.kind == "memory"
                )
                graphs.append(rebuilt.interactions)
            assert graphs[0] == graphs[1]

    asyncio.run(scenario())


def test_required_receipt_is_restored_without_promoting_the_ledger_into_candidates(configured_project: Path) -> None:
    """必要证据优先于默认台账过滤，但不能绕过 Bot 明确设置的读取范围。"""

    async def scenario() -> None:
        async with prepared_runtime(configured_project) as (runtime, _model_id):
            registry = runtime.assembly.get(OperationRegistry)
            call = request(runtime, "source-read", "query/source", {"memory_id": SOURCE})
            await registry.dispatch(call)
            receipt_id = f"{call.identity}:result"
            state = runtime.assembly.get(BotStateStore)
            before = await state.snapshot()
            goal = replace(before.goal(GOAL), checkpoint=Checkpoint(evidence_refs=(receipt_id,)))
            await state.apply(BotChange("checkpoint", before.version, (goal,)))
            memory = runtime.assembly.get(MemoryReader)
            snapshot = await memory.recall(MemoryRequest(focus_goal_ids=(GOAL,)))
            assert tuple(commit.commit_id for commit in snapshot.required) == (receipt_id,)
            assert snapshot.missing_refs == ()
            assert snapshot.recall is not None
            assert all(not item.memory_id.startswith("operation:") for item in snapshot.recall.ranking)
            assert snapshot.recall.candidate_scopes is not None
            assert f"{state.scope}/operations" not in snapshot.recall.candidate_scopes
            assert f"{state.scope}/operations" in (snapshot.recall.request.scopes or ())
            scoped = await memory.recall(
                MemoryRequest(focus_goal_ids=(GOAL,), scopes=frozenset({"test:world/experiment"}))
            )
            assert scoped.required == ()
            assert scoped.missing_refs == (receipt_id,)

    asyncio.run(scenario())
