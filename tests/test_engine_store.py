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
    EngineConfiguration,
    ModelContinuation,
    ModelRequest,
    ModelResult,
    ModelUsage,
    TaskLimits,
    TaskStatus,
    ToolCall,
    ToolExecutionRequest,
    ToolExecutorBinding,
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


def _configuration(workspace: Path) -> EngineConfiguration:
    return EngineConfiguration(
        str(workspace),
        _profiles(),
        AgentLimits(root_profile="gate", worker_profile="worker"),
        TaskLimits(8, 6, 300),
        TaskLimits(3, 2, 120),
        TriageLimits(quiet_seconds=0, max_wait_seconds=0.001),
    )


def _amp(summary: str = "hello"):
    return new_amp(
        event_type="message.received",
        session_id="session",
        summary=summary,
        data={"text": summary},
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
    bindings: tuple[ToolExecutorBinding, ...] | Callable[[AgentEngine], tuple[ToolExecutorBinding, ...]] = (),
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
    """提交 → 入口任务 → 完成：终态留存 SQLite（无文件归档，RFC 0210）。"""

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


def test_invalid_file_is_rejected(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine = _engine(tmp_path, {"gate": _Complete(), "worker": _Complete()})
        try:
            invalid = tmp_path / "inbox" / "invalid.json"
            invalid.write_text("{", encoding="utf-8")
            await engine.pump()
            rejected = tmp_path / "archive" / "inbox" / "rejected"
            assert (rejected / "invalid.json").is_file()
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
    catalog = PromptCatalog.create(soul="soul", world="world", agents={"gate": "gate", "worker": "worker"})
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


def _binding(capability: str, engine: AgentEngine) -> ToolExecutorBinding:
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

    return ToolExecutorBinding(
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
                ToolExecutorBinding(
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
