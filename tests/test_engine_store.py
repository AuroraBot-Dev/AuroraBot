# ruff: noqa: PLR2004
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING

import pytest

from src.agents.handler import ToolAgent
from src.contracts import (
    AgentContext,
    AgentDecision,
    AgentLimits,
    AgentProfile,
    CapabilityDescriptor,
    Completion,
    DelegationRequest,
    EffectToolBinding,
    EngineConfiguration,
    ModelContinuation,
    ModelRequest,
    ModelResult,
    ModelUsage,
    TaskLimits,
    TaskStatus,
    ToolCall,
    ToolExecutionRequest,
    ToolRequest,
    TriageLimits,
    new_amp,
    tool_receipt_amp,
)
from src.engine.runtime import AgentEngine
from src.prompt import PromptCatalog, PromptComposer

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _profiles() -> tuple[AgentProfile, ...]:
    return (
        AgentProfile(
            "gate",
            "test",
            "fast",
            frozenset({"test.*"}),
            can_delegate=True,
            child_profiles=frozenset({"worker"}),
        ),
        AgentProfile(
            "worker",
            "test",
            "fast",
            frozenset({"test.*"}),
            can_delegate=True,
            child_profiles=frozenset({"worker"}),
        ),
    )


def _configuration(
    workspace: Path,
    *,
    model_concurrency: int = 4,
    triage: TriageLimits | None = None,
) -> EngineConfiguration:
    return EngineConfiguration(
        str(workspace),
        _profiles(),
        AgentLimits(root_profile="gate", worker_profile="worker", model_concurrency=model_concurrency),
        TaskLimits(8, 6, 300),
        TaskLimits(3, 2, 120),
        triage or TriageLimits(quiet_seconds=0, max_wait_seconds=0.001),
    )


def _amp(summary: str = "hello", *, session_id: str = "session", attention: str | None = None):
    data = {"text": summary}
    if attention is not None:
        data["attention"] = attention
    return new_amp(
        event_type="message.received",
        session_id=session_id,
        summary=summary,
        data=data,
        source_app="test",
        source_instance="test",
    )


class _Complete:
    def handle(self, context: AgentContext) -> AgentDecision:
        return AgentDecision(completion=Completion(f"done: {context.agent.assignment}"))


class _UnusedProvider:
    async def complete(self, request: ModelRequest) -> ModelResult:
        return ModelResult(
            request.role,
            frozenset({"chat", "structured_output"}),
            "normalized",
            "",
            {"action": "process", "summary": "hello", "reason": "test"},
            ModelUsage(),
            0.0,
        )


async def _pump_until_terminal(engine: AgentEngine, task_id: str, max_rounds: int = 20) -> None:
    for _ in range(max_rounds):
        task = engine.get_task(task_id)
        if task is None or task.terminal:
            return
        await engine.pump()
        await asyncio.sleep(0)


def _engine(
    workspace: Path,
    handlers: dict[str, object],
    provider: object | None = None,
    bindings: tuple[EffectToolBinding, ...] | Callable[[AgentEngine], tuple[EffectToolBinding, ...]] = (),
) -> AgentEngine:
    engine = AgentEngine(
        _configuration(workspace),
        dict(handlers),  # type: ignore[dict-item]
        model_provider=provider if provider is not None else _UnusedProvider(),  # type: ignore[arg-type]
    )
    resolved = bindings(engine) if callable(bindings) else bindings
    engine.bind_tool_executors(resolved)
    return engine


def test_amp_creates_terminal_record_and_deduplicates_task(tmp_path: Path) -> None:
    """提交 → 入口任务 → 完成：终态留存 SQLite（无文件归档）。"""

    async def scenario() -> None:
        engine = _engine(tmp_path, {"gate": _Complete(), "worker": _Complete()})
        try:
            amp = _amp().to_dict()
            await engine.submit_amp(amp)
            await asyncio.sleep(0.001)
            first = await engine.pump()
            task_id = first["admitted_task_ids"][0]
            await _pump_until_terminal(engine, task_id)

            task = engine.get_task(task_id)
            assert task is not None and task.status == TaskStatus.COMPLETED

            detail = engine.task_detail(task_id)
            assert detail is not None
            assert detail["events"][0]["type"] == "task.started"

            # 重复 AMP 幂等：不产生新任务
            await engine.submit_amp(amp)
            await asyncio.sleep(0.001)
            replay = await engine.pump()
            assert replay["admitted_task_ids"] == ()
        finally:
            await engine.shutdown()

    asyncio.run(scenario())


def test_delegation_children_report_to_parent(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.agent.parent_agent_id is None and context.message.type == "task.started":
                return AgentDecision(delegations=(DelegationRequest("first"), DelegationRequest("second")))
            if context.agent.parent_agent_id is not None:
                return AgentDecision(completion=Completion(context.agent.assignment))
            completed = int(context.agent.state.get("completed", 0)) + 1
            if completed == 1:
                return AgentDecision(wait_for_children=True, state_patch={"completed": completed})
            return AgentDecision(completion=Completion("all children reported"), state_patch={"completed": completed})

    async def scenario() -> None:
        engine = _engine(tmp_path, {"gate": Handler(), "worker": Handler()})
        try:
            await engine.submit_amp(_amp().to_dict())
            await asyncio.sleep(0.001)
            result = await engine.pump()
            task_id = result["admitted_task_ids"][0]
            await _pump_until_terminal(engine, task_id, max_rounds=30)
            task = engine.get_task(task_id)
            assert task is not None and task.status == TaskStatus.COMPLETED
            assert len(engine.store.agents()) == 3
        finally:
            await engine.shutdown()

    asyncio.run(scenario())


def test_tool_success_resumes_agent_and_duplicate_is_idempotent(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.message.type == "tool.succeeded":
                return AgentDecision(completion=Completion("tool handled"))
            return AgentDecision(tool_request=ToolRequest("test.reply", {"text": "hello"}))

    async def scenario() -> None:
        engine = _engine(
            tmp_path,
            {"gate": Handler(), "worker": Handler()},
            bindings=lambda engine: (_binding("test.reply", engine),),
        )
        try:
            await engine.submit_amp(_amp().to_dict())
            await asyncio.sleep(0.001)
            result = await engine.pump()
            task_id = result["admitted_task_ids"][0]
            await _pump_until_terminal(engine, task_id)
            task = engine.get_task(task_id)
            assert task is not None and task.status == TaskStatus.COMPLETED
        finally:
            await engine.shutdown()

    asyncio.run(scenario())


def test_complete_task_tool_finishes_without_resume(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            _ = context
            return AgentDecision(tool_request=ToolRequest("test.reply", {"text": "done"}, complete_task=True))

    async def scenario() -> None:
        engine = _engine(
            tmp_path,
            {"gate": Handler(), "worker": Handler()},
            bindings=lambda engine: (_binding("test.reply", engine),),
        )
        try:
            await engine.submit_amp(_amp().to_dict())
            await asyncio.sleep(0.001)
            result = await engine.pump()
            task_id = result["admitted_task_ids"][0]
            await _pump_until_terminal(engine, task_id)
            task = engine.get_task(task_id)
            assert task is not None and task.status == TaskStatus.COMPLETED
        finally:
            await engine.shutdown()

    asyncio.run(scenario())


def test_engine_persists_and_executes_every_model_tool_call(tmp_path: Path) -> None:
    catalog = PromptCatalog(soul="soul", world="world", agents={"gate": "gate", "worker": "worker"})
    agent = ToolAgent(composer=PromptComposer(catalog))
    engine = _engine(
        tmp_path,
        {"gate": agent, "worker": agent},
        bindings=lambda engine: (_binding("test.first", engine), _binding("test.second", engine)),
    )

    class ChainProvider:
        """第一次调用返回两个工具调用；续轮返回纯文本完成。"""

        def __init__(self) -> None:
            self._calls = 0

        async def complete(self, _request: ModelRequest) -> ModelResult:
            self._calls += 1
            if self._calls == 1:
                return ModelResult(
                    "model",
                    frozenset({"chat", "tools"}),
                    "native",
                    "",
                    None,
                    ModelUsage(),
                    0.0,
                    tool_calls=(
                        ToolCall("first-call", "test.first", {"value": 1}),
                        ToolCall("second-call", "test.second", {"value": 2}),
                    ),
                    continuation=ModelContinuation(
                        "provider",
                        "responses",
                        (
                            {"type": "function_call", "call_id": "first-call", "name": "test.first"},
                            {"type": "function_call", "call_id": "second-call", "name": "test.second"},
                        ),
                    ),
                )
            return ModelResult("model", frozenset({"chat", "tools"}), "native", "all done", None, ModelUsage(), 0.0)

    engine._model_provider = ChainProvider()  # type: ignore[assignment]
    try:
        asyncio.run(_chain_scenario(engine))
    finally:
        asyncio.run(engine.shutdown())


async def _chain_scenario(engine: AgentEngine) -> None:
    await engine.submit_amp(_amp().to_dict())
    await asyncio.sleep(0.001)
    result = await engine.pump()
    task_id = result["admitted_task_ids"][0]
    for _ in range(12):
        task = engine.get_task(task_id)
        if task is None or task.terminal:
            break
        await engine.pump()
        await asyncio.sleep(0)
    task = engine.get_task(task_id)
    assert task is not None and task.status == TaskStatus.COMPLETED
    assert task.tool_calls == 2
    assert task.model_calls == 2


def _binding(capability: str, engine: AgentEngine) -> EffectToolBinding:
    class _Executor:
        async def execute_tool(self, request: ToolExecutionRequest) -> None:
            await engine.submit_amp(
                tool_receipt_amp(
                    status="succeeded",
                    request=request,
                    summary="done",
                    source_app="test",
                    source_instance="local",
                    result={"ok": True},
                )
            )

    return EffectToolBinding(
        CapabilityDescriptor(capability, "reply", {"type": "object"}),
        _Executor(),
        "test",
        "local",
    )


def test_model_activity_completion_and_failure_are_auditable(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.message.type == "model.completed":
                return AgentDecision(completion=Completion(str(context.message.payload["text"])))
            if context.message.type == "model.failed":
                return AgentDecision(failure=str(context.message.payload["error"]))
            return AgentDecision(model_request=ModelRequest(role="fast", messages=()))

    class Provider:
        def __init__(self) -> None:
            self._calls = 0

        async def complete(self, _request: ModelRequest) -> ModelResult:
            self._calls += 1
            if self._calls == 1:
                return ModelResult("fake", frozenset({"chat"}), "normalized", "answer", None, ModelUsage(), 0)
            raise RuntimeError("provider unavailable")

    async def scenario() -> None:
        engine = _engine(tmp_path, {"gate": Handler(), "worker": Handler()}, provider=Provider())
        try:
            await engine.submit_amp(_amp("success").to_dict())
            await asyncio.sleep(0.001)
            result = await engine.pump()
            task_id = result["admitted_task_ids"][0]
            await _pump_until_terminal(engine, task_id)
            assert engine.get_task(task_id) is not None
            assert engine.get_task(task_id).status == TaskStatus.COMPLETED  # type: ignore[union-attr]

            await engine.submit_amp(_amp("failure").to_dict())
            await asyncio.sleep(0.001)
            result = await engine.pump()
            task_id = result["admitted_task_ids"][0]
            await _pump_until_terminal(engine, task_id)
            assert engine.get_task(task_id) is not None
            assert engine.get_task(task_id).status == TaskStatus.ERROR  # type: ignore[union-attr]
        finally:
            await engine.shutdown()

    asyncio.run(scenario())


def test_output_stream_returns_model_text_and_failures_ordered_by_cursor(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.message.type == "model.completed":
                return AgentDecision(completion=Completion(str(context.message.payload["text"])))
            if context.message.type == "model.failed":
                return AgentDecision(failure=str(context.message.payload["error"]))
            return AgentDecision(model_request=ModelRequest(role="fast", messages=()))

    class Provider:
        def __init__(self) -> None:
            self._calls = 0

        async def complete(self, _request: ModelRequest) -> ModelResult:
            self._calls += 1
            if self._calls == 1:
                return ModelResult("fake", frozenset({"chat"}), "normalized", "answer one", None, ModelUsage(), 0)
            raise RuntimeError("provider unavailable")

    async def scenario() -> None:
        engine = _engine(tmp_path, {"gate": Handler(), "worker": Handler()}, provider=Provider())
        try:
            await engine.submit_amp(_amp("first").to_dict())
            await asyncio.sleep(0.001)
            result = await engine.pump()
            task_id = result["admitted_task_ids"][0]
            await _pump_until_terminal(engine, task_id)

            page = engine.output_stream()
            assert [item.text for item in page.items] == ["answer one"]
            assert all(item.kind == "model" for item in page.items)
            assert page.next_cursor == page.items[-1].cursor

            await engine.submit_amp(_amp("second").to_dict())
            await asyncio.sleep(0.001)
            result = await engine.pump()
            task_id = result["admitted_task_ids"][0]
            await _pump_until_terminal(engine, task_id)

            page = engine.output_stream(page.next_cursor)
            assert len(page.items) == 1
            assert page.items[0].kind == "error"
            assert page.items[0].text == "RuntimeError: provider unavailable"

            assert engine.output_stream(page.next_cursor).items == ()
        finally:
            await engine.shutdown()

    asyncio.run(scenario())


def test_session_keeps_ordinary_amp_as_delta_and_publishes_before_followup(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.message.type == "model.completed":
                return AgentDecision(completion=Completion(str(context.message.payload["text"])))
            return AgentDecision(model_request=ModelRequest(role="fast", messages=()))

    class Provider:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = 0

        async def complete(self, request: ModelRequest) -> ModelResult:
            _ = request
            self.calls += 1
            call = self.calls
            if call == 1:
                self.started.set()
                await self.release.wait()
            return ModelResult("fake", frozenset({"chat"}), "normalized", f"answer {call}", None, ModelUsage(), 0)

    async def scenario() -> None:
        provider = Provider()
        engine = _engine(tmp_path, {"gate": Handler(), "worker": Handler()}, provider=provider)
        try:
            await engine.submit_amp(_amp("first").to_dict())
            first = await engine.pump()
            first_task_id = first["admitted_task_ids"][0]
            await asyncio.wait_for(provider.started.wait(), 1)

            await engine.submit_amp(_amp("ordinary follow-up").to_dict())
            lane = engine.store.session_lane("session")
            assert lane is not None
            assert lane["active_task_id"] == first_task_id
            assert lane["observed_revision"] == 2
            assert lane["generation_watermark"] == 1
            assert engine.get_task(first_task_id).status == TaskStatus.ACTIVE  # type: ignore[union-attr]

            provider.release.set()
            await _pump_until_terminal(engine, first_task_id)
            first_page = engine.output_stream()
            assert [item.text for item in first_page.items] == ["answer 1"]

            followup = await engine.pump()
            second_task_id = followup["admitted_task_ids"][0]
            await _pump_until_terminal(engine, second_task_id)
            second_page = engine.output_stream(first_page.next_cursor)
            assert [item.text for item in second_page.items] == ["answer 2"]
        finally:
            await engine.shutdown()

    asyncio.run(scenario())


def test_direct_amp_supersedes_generation_cancels_provider_and_hides_old_output(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.message.type == "model.completed":
                return AgentDecision(completion=Completion(str(context.message.payload["text"])))
            return AgentDecision(model_request=ModelRequest(role="fast", messages=(), cancel_policy="supersedable"))

    class Provider:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()
            self.second_started = asyncio.Event()
            self.release_second = asyncio.Event()
            self.calls = 0

        async def complete(self, request: ModelRequest) -> ModelResult:
            _ = request
            self.calls += 1
            if self.calls == 1:
                self.started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise
            if self.calls == 2:
                self.second_started.set()
                await self.release_second.wait()
            return ModelResult("fake", frozenset({"chat"}), "normalized", "new answer", None, ModelUsage(), 0)

    async def scenario() -> None:
        provider = Provider()
        configuration = _configuration(
            tmp_path,
            triage=TriageLimits(
                quiet_seconds=0,
                max_wait_seconds=0.001,
                max_interrupts=1,
                max_generation_seconds=30,
            ),
        )
        engine = AgentEngine(
            configuration,
            {"gate": Handler(), "worker": Handler()},
            model_provider=provider,
        )
        engine.bind_tool_executors(())
        try:
            await engine.submit_amp(_amp("stale").to_dict())
            first = await engine.pump()
            stale_task_id = first["admitted_task_ids"][0]
            await asyncio.wait_for(provider.started.wait(), 1)

            await engine.submit_amp(_amp("correction", attention="correction").to_dict())
            await asyncio.wait_for(provider.cancelled.wait(), 1)
            stale = engine.get_task(stale_task_id)
            assert stale is not None and stale.status == TaskStatus.CANCELLED
            assert stale.termination_reason == "superseded_by_revision:2"
            stale_events = engine.store.events_for_task(stale_task_id)
            assert "generation.late_result_ignored" in {event["type"] for event in stale_events}
            with engine.store.connect() as connection:
                statuses = {
                    row["status"]
                    for row in connection.execute(
                        "SELECT status FROM activities WHERE task_id = ?",
                        (stale_task_id,),
                    )
                }
            assert "SUPERSEDED" in statuses
            assert engine.output_stream().items == ()

            replacement = await engine.pump()
            replacement_task_id = replacement["admitted_task_ids"][0]
            await asyncio.wait_for(provider.second_started.wait(), 1)

            await engine.submit_amp(_amp("another urgent message", attention="urgent").to_dict())
            await asyncio.sleep(0)
            current = engine.get_task(replacement_task_id)
            assert current is not None and current.status == TaskStatus.ACTIVE
            assert provider.calls == 2

            provider.release_second.set()
            await _pump_until_terminal(engine, replacement_task_id)
            page = engine.output_stream()
            assert [item.text for item in page.items] == ["new answer"]
            assert page.items[0].task_id == replacement_task_id
            exported = engine.session_export("session")
            assert exported is not None
            assert [item["text"] for item in exported["outputs"]] == ["new answer"]
            lane = engine.store.session_lane("session")
            assert lane is not None and lane["committed_revision"] == 2
            assert lane["observed_revision"] == 3
            assert lane["interrupt_count"] == 0
        finally:
            await engine.shutdown()

    asyncio.run(scenario())


def test_processing_tool_blocks_supersede_until_irreversible_effect_finishes(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            _ = context
            return AgentDecision(tool_request=ToolRequest("test.effect", {}, complete_task=True))

    class Executor:
        def __init__(self, engine: AgentEngine) -> None:
            self.engine = engine
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def execute_tool(self, request: ToolExecutionRequest) -> None:
            self.started.set()
            await self.release.wait()
            await self.engine.submit_amp(
                tool_receipt_amp(
                    status="succeeded",
                    request=request,
                    summary="effect committed",
                    source_app="test",
                    source_instance="local",
                    result={"ok": True},
                )
            )

    async def scenario() -> None:
        engine = AgentEngine(
            _configuration(tmp_path),
            {"gate": Handler(), "worker": Handler()},
            model_provider=_UnusedProvider(),
        )
        executor = Executor(engine)
        engine.bind_tool_executors(
            (
                EffectToolBinding(
                    CapabilityDescriptor("test.effect", "effect", {"type": "object"}),
                    executor,
                    "test",
                    "local",
                ),
            )
        )
        try:
            await engine.submit_amp(_amp("start effect").to_dict())
            first = await engine.pump()
            task_id = first["admitted_task_ids"][0]
            await asyncio.wait_for(executor.started.wait(), 1)

            await engine.submit_amp(_amp("correction", attention="correction").to_dict())
            task = engine.get_task(task_id)
            lane = engine.store.session_lane("session")
            assert task is not None and task.status == TaskStatus.ACTIVE
            assert lane is not None and lane["active_task_id"] == task_id
            assert lane["observed_revision"] == 2
            assert lane["generation_watermark"] == 1

            executor.release.set()
            await _pump_until_terminal(engine, task_id)
            task = engine.get_task(task_id)
            assert task is not None and task.status == TaskStatus.COMPLETED
        finally:
            executor.release.set()
            await engine.shutdown()

    asyncio.run(scenario())


def test_model_dispatcher_refills_free_slot_without_waiting_for_slow_session(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.message.type == "model.completed":
                return AgentDecision(completion=Completion(str(context.message.payload["text"])))
            return AgentDecision(model_request=ModelRequest(role="fast", messages=()))

    class Provider:
        def __init__(self) -> None:
            self.slow_started = asyncio.Event()
            self.third_started = asyncio.Event()
            self.release_slow = asyncio.Event()
            self.calls = 0

        async def complete(self, request: ModelRequest) -> ModelResult:
            _ = request
            self.calls += 1
            call = self.calls
            if call == 1:
                self.slow_started.set()
                await self.release_slow.wait()
            if call == 3:
                self.third_started.set()
            return ModelResult("fake", frozenset({"chat"}), "normalized", f"answer {call}", None, ModelUsage(), 0)

    async def scenario() -> None:
        provider = Provider()
        configuration = _configuration(tmp_path, model_concurrency=2)
        engine = AgentEngine(
            configuration,
            {"gate": Handler(), "worker": Handler()},
            model_provider=provider,
        )
        engine.bind_tool_executors(())
        try:
            await engine.submit_amp(_amp("one", session_id="one").to_dict())
            await engine.submit_amp(_amp("two", session_id="two").to_dict())
            await engine.pump()
            await asyncio.wait_for(provider.slow_started.wait(), 1)
            for _ in range(10):
                await engine.pump()
                await asyncio.sleep(0)
                if provider.calls >= 2:
                    break
            assert provider.calls >= 2

            await engine.submit_amp(_amp("three", session_id="three").to_dict())
            await engine.pump()
            await asyncio.wait_for(provider.third_started.wait(), 1)
            assert not provider.release_slow.is_set()
        finally:
            provider.release_slow.set()
            await engine.shutdown()

    asyncio.run(scenario())


def test_handler_exception_fails_message_and_task(tmp_path: Path) -> None:
    class Broken:
        def handle(self, context: AgentContext) -> AgentDecision:
            _ = context
            raise RuntimeError("broken handler")

    async def scenario() -> None:
        engine = _engine(tmp_path, {"gate": Broken(), "worker": Broken()})
        try:
            with pytest.raises(ValueError, match="positive"):
                await engine.pump(0)
            await engine.submit_amp(_amp().to_dict())
            await asyncio.sleep(0.001)
            result = await engine.pump()
            task_id = result["admitted_task_ids"][0]
            await _pump_until_terminal(engine, task_id)
            task = engine.get_task(task_id)
            assert result["failed_message_ids"]
            assert task is not None and task.status == TaskStatus.ERROR
            assert engine.status()["active_tasks"] == 0
        finally:
            await engine.shutdown()

    asyncio.run(scenario())


def test_handler_context_cannot_mutate_canonical_authorization_state(tmp_path: Path) -> None:
    canonical_profile = _profiles()[0]

    class Hostile:
        def handle(self, context: AgentContext) -> AgentDecision:
            with pytest.raises(FrozenInstanceError):
                context.profile.capabilities = frozenset({"*"})  # type: ignore[misc]
            object.__setattr__(context.profile, "capabilities", frozenset({"*"}))
            context.agent.state["forged"] = True
            context.message.payload["forged"] = True
            return AgentDecision(tool_request=ToolRequest("forbidden.send", {}))

    async def scenario() -> None:
        engine = _engine(
            tmp_path,
            {"gate": Hostile(), "worker": _Complete()},
            bindings=(
                EffectToolBinding(
                    CapabilityDescriptor("forbidden.send", "forbidden", {"type": "object"}),
                    _NoopExecutor(),
                    "test",
                    "local",
                ),
            ),
        )
        try:
            await engine.submit_amp(_amp().to_dict())
            await asyncio.sleep(0.001)
            result = await engine.pump()
            task_id = result["admitted_task_ids"][0]
            await _pump_until_terminal(engine, task_id)
            task = engine.get_task(task_id)
            agent = engine.get_agent(task.root_agent_id) if task is not None else None
            assert result["failed_message_ids"]
            assert task is not None and task.status == TaskStatus.ERROR
            assert agent is not None and "forged" not in agent.state
            assert engine._profiles["gate"].capabilities == canonical_profile.capabilities == frozenset({"test.*"})
        finally:
            await engine.shutdown()

    asyncio.run(scenario())


class _NoopExecutor:
    async def execute_tool(self, request: ToolExecutionRequest) -> None:  # noqa: ARG002
        return None
