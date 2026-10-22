from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from aurora_agent import Agent, RunRequest, RunResult, RunSnapshot
from aurora_bot.contracts.process import DEFAULT_PROCESS, CognitionProcess
from aurora_bot.engine.ledger import RunLedger
from aurora_bot.engine.session import PREFIX, BoundTool, RunSession
from aurora_bot.utils import get_logger
from aurora_kernel.tasks import raise_with_cleanup, wait_for_completion

if TYPE_CHECKING:
    from collections.abc import Callable

    from aurora_bot.contracts import CognitionRequest
    from aurora_kernel import Context

_logger = get_logger(__name__)


class CognitionEngine:
    def __init__(self, ctx: Context, world: Any, *, bot_id: str, process: CognitionProcess = DEFAULT_PROCESS) -> None:
        if process.strategy != "react":
            raise ValueError(f"默认执行器不支持认知策略：{process.strategy}")
        self._ctx = ctx
        self._world = world
        self._bot_id = bot_id
        self._process = process
        self._active: dict[str, RunSession] = {}

    @property
    def process_definition(self) -> CognitionProcess:
        return self._process

    def snapshot(self, run_id: str) -> RunSnapshot:
        run = self._active[run_id].run
        assert run is not None
        return run.snapshot()

    def append_message(self, run_id: str, message: str) -> None:
        run = self._active[run_id].run
        assert run is not None
        run.append_message(message)

    def cancel(self, run_id: str) -> None:
        run = self._active[run_id].run
        assert run is not None
        run.cancel()

    async def execute(
        self, request: CognitionRequest, observer: Callable[[RunSnapshot], None] | None = None
    ) -> RunResult:
        if request.agent is None:
            raise ValueError("认知请求必须明确 Agent")
        request = replace(request, run_id=request.run_id or uuid4().hex)
        assert request.run_id is not None
        if request.run_id in self._active:
            raise ValueError(f"认知运行已存在：{request.run_id}")
        definition = self._ctx.call(f"{PREFIX}agents:get", request.agent)
        tools = self._ctx.call(f"{PREFIX}tools:definitions_for", definition.tools)
        ledger = RunLedger(self._world, self._bot_id, request, definition, self._process, tools)
        session = RunSession(self._ctx, ledger)
        agent = Agent(
            instructions=definition.description,
            model=definition.model,
            provider=session,
            assembler=session,
            policy=session,
            tools=tuple(BoundTool(session, tool) for tool in tools),
            limits=self._process.limits,
        )
        session.run = agent.create(RunRequest(request.message, run_id=request.run_id))
        self._active[request.run_id] = session
        try:
            await ledger.start()
            _logger.info("认知运行开始 run_id={}", request.run_id)
            return await self._drive(session, observer)
        finally:
            self._active.pop(request.run_id, None)

    async def _drive(self, session: RunSession, observer: Callable[[RunSnapshot], None] | None) -> RunResult:
        run = session.run
        assert run is not None
        failure: BaseException | None = None
        try:
            while not run.snapshot().status.terminal:
                await self._ctx.acall(f"{PREFIX}engine:before_step", run.snapshot())
                snapshot = await run.step()
                await session.record_calls(snapshot)
                if snapshot.status.terminal:
                    await session.ledger.finish(snapshot)
                if observer is not None:
                    observer(snapshot)
                await self._ctx.acall(f"{PREFIX}engine:after_step", snapshot)
        except BaseException as error:
            failure = error
        if not run.snapshot().status.terminal:
            run.cancel()
        snapshot = run.snapshot()
        settlement = asyncio.create_task(self._settle(session, snapshot, failure))
        try:
            _, interrupted = await wait_for_completion(settlement)
        except BaseException as error:
            if failure is not None:
                raise_with_cleanup(failure, (error,))
            raise
        if failure is not None:
            raise_with_cleanup(failure, (), interrupted)
        if interrupted is not None:
            raise interrupted
        assert snapshot.result is not None
        return snapshot.result

    async def _settle(self, session: RunSession, snapshot: RunSnapshot, failure: BaseException | None) -> None:
        await session.record_calls(snapshot)
        await session.ledger.finish(snapshot, failure)
        _logger.info("认知运行结束 run_id={} status={}", snapshot.run_id, snapshot.status.value)
