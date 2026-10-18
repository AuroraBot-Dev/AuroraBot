"""通过真实 Bot 装配产生一次读取、目标和后续结果。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from test_assembly import FakeModel

from aurora import load_config
from src.contracts import TreeLaunchRequest, WorldFrontier
from src.contracts.bot import BotChange, Checkpoint, Goal
from src.contracts.operation import OperationKind, OperationRequest
from src.contracts.pkgs.bot import BotStateStore
from src.contracts.resource import ResourceKey, ResourceRef
from src.runtime import assemble_runtime

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from src.runtime.core import AuroraRuntime

GOAL = "aurora:goal/check"
SOURCE = "experiment-started"
OUTCOME = "experiment-result"


@asynccontextmanager
async def prepared_runtime(project: Path) -> AsyncIterator[tuple[AuroraRuntime, str]]:
    """所有输入先进入世界，运行后再追加评估依据。"""
    runtime = assemble_runtime(load_config(project), FakeModel(), output=lambda _: None)
    try:
        await runtime.world.initialize()
        await runtime.world.append_commit(
            commit_id=SOURCE,
            kind="experiment.started",
            source="test",
            summary="实验操作已经发起",
            scopes=frozenset({"test:world/experiment"}),
            based_on=WorldFrontier(),
            data={"operation_id": "operation-7"},
        )
        state = runtime.assembly.get(BotStateStore)
        goal = Goal(GOAL, "核对实验结果", "结果已确认", checkpoint=Checkpoint(evidence_refs=(SOURCE,)))
        await state.apply(BotChange("goal", 0, (goal,)))
        tree = await runtime.launch_tree(TreeLaunchRequest("核对实验", tree_id="memory-audit", focus_goal_ids=(GOAL,)))
        identity = f"{tree.tree_id}:{tree.root_id}:model:0:requested"
        await runtime.world.append_commit(
            commit_id=OUTCOME,
            kind="experiment.completed",
            source="test",
            summary="实验结果已完成核对",
            scopes=frozenset({"test:world/experiment"}),
            based_on=WorldFrontier(),
            data={"success": True},
        )
        yield runtime, identity
    finally:
        await runtime.world.close()


def request(runtime: AuroraRuntime, identity: str, path: str, arguments: dict[str, Any]) -> OperationRequest:
    """直接入口和工具入口使用同一资源及主体身份。"""
    key = ResourceKey.parse(f"aurora:memory/{path}")
    return OperationRequest(
        identity,
        runtime.assembly.get(BotStateStore).bot_id,
        "test:evaluator",
        ResourceRef(key),
        OperationKind(key.kind),
        arguments,
    )


def feedback_arguments(model_request_id: str) -> dict[str, Any]:
    """明确评价先前载入的来源，并引用读取之后获知的结果。"""
    return {
        "model_request_id": model_request_id,
        "memory_id": SOURCE,
        "goal_id": GOAL,
        "helpful": True,
        "reason": "先前发起记录避免了重复执行，后续结果已经确认",
        "evidence_refs": [OUTCOME],
    }
