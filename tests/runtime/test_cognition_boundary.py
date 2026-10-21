"""Bot 的认知入口、终端和恢复身份不要求执行器创建委派树。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from aurora_bot.contracts import CognitionRequest, CognitionResult, WorldFrontier
from aurora_bot.contracts.pkgs.engine import CognitionRunner
from aurora_bot.contracts.process import CognitionProcess
from aurora_bot.runtime import assemble_runtime
from aurora_bot.world import SqlAlchemyWorldJournal
from aurora_cli import load_config

if TYPE_CHECKING:
    from pathlib import Path


class DirectRunner:
    """直接处理一次请求并登记结果，不创建 AgentNode 或 AgentTree。"""

    process_definition = CognitionProcess(strategy="direct")
    tool_definitions = ()

    def __init__(self, world: SqlAlchemyWorldJournal) -> None:
        self.world = world
        self.requests: list[CognitionRequest] = []

    async def execute(self, request: CognitionRequest, observer: Any = None) -> CognitionResult:
        assert request.run_id is not None
        self.requests.append(request)
        # 运行身份与结果审计是执行器契约；委派拓扑不是契约的一部分。
        for stage in ("started", "completed"):
            await self.world.append_commit(
                commit_id=f"{request.run_id}:tree:{stage}",
                kind=f"engine.tree.{stage}",
                source="direct",
                summary="认知请求已处理",
                scopes=frozenset({f"aurora:run/{request.run_id}"}),
                based_on=request.frontier,
                data={"tree_id": request.run_id, "caused_by": request.caused_by},
            )
        return CognitionResult(request.run_id, "直接执行完成")


def test_runtime_accepts_executor_without_tree_and_preserves_duplicate_protection(configured_project: Path) -> None:
    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(configured_project / "direct.sqlite3")
        runner = DirectRunner(world)
        runtime = assemble_runtime(load_config(configured_project), world=world, instances=((CognitionRunner, runner),))
        try:
            result = await runtime.run("请求处理", run_id="direct")
            assert result == CognitionResult("direct", "直接执行完成")
            request = runner.requests[0]
            assert request.agent == runtime.root.agent
            assert request.caused_by is not None
            cause = await world.commit(request.caused_by)
            assert cause is not None and cause.kind == "runtime.input"
            assert request.frontier == WorldFrontier(cause.scopes)
            with pytest.raises(ValueError, match="已存在"):
                await runtime.run("禁止重复执行", run_id="direct")
            assert len(runner.requests) == 1
            assert runtime.runtime_status()["runs"]["completed"] == 1
            terminal = await runtime.terminal.dispatch_terminal(cause.summary, commit=cause)
            assert terminal.text == "直接执行完成"
            assert not terminal.is_error
        finally:
            await world.close()

    asyncio.run(scenario())
