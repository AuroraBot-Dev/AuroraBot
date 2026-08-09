"""AgentEngine 最小因果闭环。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.agents.triage import TriageAgent
from src.contracts import (
    AgentContext,
    AgentDecision,
    AgentLimits,
    AgentProfile,
    CapabilityDescriptor,
    Completion,
    EngineConfiguration,
    MemoryContextSnapshot,
    MemoryEntry,
    MemoryQuery,
    ModelRequest,
    ModelResult,
    ModelUsage,
    TaskLimits,
    ToolCall,
    ToolExecutionRequest,
    ToolExecutorBinding,
    ToolRequest,
    TriageLimits,
    new_amp,
    tool_receipt_amp,
)
from src.engine.runtime import AgentEngine

if TYPE_CHECKING:
    from pathlib import Path


class _CompletingHandler:
    def handle(self, context: AgentContext) -> AgentDecision:
        return AgentDecision(completion=Completion(f"completed: {context.task.root_summary}"))


class _UnusedModelProvider:
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


def test_engine_owns_complete_pump(tmp_path: Path) -> None:
    async def exercise() -> None:
        profile = AgentProfile(
            id="test.root",
            implementation="unused",
            model_role="test",
            capabilities=frozenset(),
            can_delegate=False,
            child_profiles=frozenset(),
        )
        limits = AgentLimits(root_profile=profile.id, worker_profile=profile.id)
        configuration = EngineConfiguration(
            workspace=str(tmp_path / "engine"),
            profiles=(profile,),
            limits=limits,
            interactive_budget=TaskLimits(1, 1, 30.0),
            autonomous_budget=TaskLimits(1, 1, 30.0),
            triage=TriageLimits(quiet_seconds=0, max_wait_seconds=0.001),
        )
        engine = AgentEngine(
            configuration,
            {profile.id: _CompletingHandler()},
            model_provider=_UnusedModelProvider(),
        )
        engine.bind_tool_executors(())
        try:
            message_id = await engine.submit_amp(
                new_amp(
                    event_type="message.received",
                    session_id="test-session",
                    summary="hello",
                    data={"text": "hello"},
                    source_app="test",
                    source_instance="local",
                ).to_dict()
            )
            assert engine.status()["inbox_events"] == 1
            result = await engine.pump()

            assert message_id
            assert len(result["admitted_task_ids"]) == 1
            assert len(result["processed_message_ids"]) == 1
            task = engine.task_detail(result["admitted_task_ids"][0])
            assert task is not None
            assert task["task"]["status"] == "COMPLETED"
        finally:
            await engine.shutdown()

    asyncio.run(exercise())


def test_engine_recalls_before_handler_and_remembers_only_interactive_completion(tmp_path: Path) -> None:
    events: list[tuple[str, object]] = []

    class Memory:
        async def recall(self, query: MemoryQuery) -> MemoryContextSnapshot:
            events.append(("recall", query))
            return MemoryContextSnapshot(relevant_facts=(f"memory:{query.query}",))

        async def remember(self, entry: MemoryEntry) -> bool:
            events.append(("remember", entry))
            return True

        async def append_turn(self, scope: str, *, role: str, content: str, at: str) -> None:  # noqa: ARG002
            events.append(("append_turn", role))

    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            events.append(("handler", context.task.root_summary))
            assert context.memory.relevant_facts == (f"memory:{context.task.root_summary}",)
            return AgentDecision(completion=Completion(f"completed: {context.task.root_summary}"))

    async def exercise() -> None:
        profile = AgentProfile(
            "test.root",
            "unused",
            "test",
            frozenset(),
            can_delegate=False,
            child_profiles=frozenset(),
        )
        configuration = EngineConfiguration(
            workspace=str(tmp_path / "engine"),
            profiles=(profile,),
            limits=AgentLimits(root_profile=profile.id, worker_profile=profile.id),
            interactive_budget=TaskLimits(1, 1, 30.0),
            autonomous_budget=TaskLimits(1, 1, 30.0),
            triage=TriageLimits(quiet_seconds=0, max_wait_seconds=0.001),
        )
        engine = AgentEngine(
            configuration,
            {profile.id: Handler()},
            model_provider=_UnusedModelProvider(),
            memory_store=Memory(),
        )
        engine.bind_tool_executors(())
        try:
            await engine.submit_amp(
                new_amp(
                    event_type="message.received",
                    session_id="interactive",
                    summary="hello",
                    data={"text": "hello"},
                    source_app="test",
                    source_instance="local",
                ).to_dict()
            )
            interactive = await engine.pump()
            await asyncio.sleep(0)  # 让异步记忆投影任务执行（单循环）
            interactive_id = interactive["admitted_task_ids"][0]
            # user 窗口写入 → recall → handler → assistant 窗口写入
            assert [name for name, _value in events[:3]] == ["append_turn", "recall", "handler"]
            remembered = [value for name, value in events if name == "remember"]
            assert [entry.task_id for entry in remembered if isinstance(entry, MemoryEntry)] == [interactive_id]
            recalled = next(value for name, value in events if name == "recall")
            assert isinstance(recalled, MemoryQuery) and recalled.scope == "interactive"

            events.clear()
            await engine.submit_amp(
                new_amp(
                    event_type="system.tick",
                    session_id="autonomy",
                    summary="tick",
                    data={},
                    source_app="engine",
                    source_instance="local",
                ).to_dict()
            )
            autonomous = await engine.pump()
            autonomous_id = autonomous["admitted_task_ids"][0]
            assert [name for name, _value in events[:3]] == ["append_turn", "recall", "handler"]
            remembered = [value for name, value in events if name == "remember"]
            assert all(isinstance(entry, MemoryEntry) and entry.task_id != autonomous_id for entry in remembered)
        finally:
            await engine.shutdown()

    asyncio.run(exercise())


def test_external_input_does_not_cancel_an_autonomous_task(tmp_path: Path) -> None:
    class ModelRequestingHandler:
        def handle(self, context: AgentContext) -> AgentDecision:
            _ = context
            return AgentDecision(model_request=ModelRequest(role="test", messages=()))

    async def exercise() -> None:
        profile = AgentProfile(
            "test.root",
            "unused",
            "test",
            frozenset(),
            can_delegate=False,
            child_profiles=frozenset(),
        )
        configuration = EngineConfiguration(
            workspace=str(tmp_path / "engine"),
            profiles=(profile,),
            limits=AgentLimits(root_profile=profile.id, worker_profile=profile.id),
            interactive_budget=TaskLimits(4, 4, 30.0),
            autonomous_budget=TaskLimits(4, 4, 30.0),
            triage=TriageLimits(quiet_seconds=0, max_wait_seconds=0.001),
        )
        engine = AgentEngine(
            configuration,
            {profile.id: ModelRequestingHandler()},
            model_provider=_UnusedModelProvider(),
        )
        engine.bind_tool_executors(())
        try:
            await engine.submit_amp(
                new_amp(
                    event_type="system.tick",
                    session_id="autonomy",
                    summary="tick",
                    data={},
                    source_app="engine",
                    source_instance="local",
                ).to_dict()
            )
            autonomous = await engine.pump()
            task_id = autonomous["admitted_task_ids"][0]

            await engine.submit_amp(
                new_amp(
                    event_type="message.received",
                    session_id="interactive",
                    summary="hello",
                    data={"text": "hello"},
                    source_app="test",
                    source_instance="local",
                ).to_dict()
            )
            detail = engine.task_detail(task_id)
            assert detail is not None
            assert detail["task"]["status"] == "ACTIVE"
        finally:
            await engine.shutdown()

    asyncio.run(exercise())


def test_engine_records_session_causality_in_sqlite(tmp_path: Path) -> None:
    """会话可读性由 causal_events 提供，不再写 JSONL。"""

    async def exercise() -> None:
        profile = AgentProfile(
            id="test.root",
            implementation="unused",
            model_role="test",
            capabilities=frozenset(),
            can_delegate=False,
            child_profiles=frozenset(),
        )
        configuration = EngineConfiguration(
            workspace=str(tmp_path / "engine"),
            profiles=(profile,),
            limits=AgentLimits(root_profile=profile.id, worker_profile=profile.id),
            interactive_budget=TaskLimits(1, 1, 30.0),
            autonomous_budget=TaskLimits(1, 1, 30.0),
            triage=TriageLimits(quiet_seconds=0, max_wait_seconds=0.001),
        )
        engine = AgentEngine(
            configuration,
            {profile.id: _CompletingHandler()},
            model_provider=_UnusedModelProvider(),
        )
        engine.bind_tool_executors(())
        try:
            await engine.submit_amp(
                new_amp(
                    event_type="message.received",
                    session_id="group/私聊:10001",
                    summary="hello",
                    data={"text": "hello"},
                    source_app="org.aurora.qq",
                    source_instance="mcp:org.aurora.qq",
                ).to_dict()
            )
            result = await engine.pump()
            assert len(result["admitted_task_ids"]) == 1
            task_id = result["admitted_task_ids"][0]
            detail = engine.task_detail(task_id)
            assert detail is not None
            types = [event["type"] for event in detail["events"]]
            assert types == ["task.started", "agent.complete"]
            assert not (tmp_path / "engine" / "sessions").exists()
        finally:
            await engine.shutdown()

    asyncio.run(exercise())


class _ToolingModelProvider:
    async def complete(self, request: ModelRequest) -> ModelResult:
        if request.output_schema is not None:
            return ModelResult(
                request.role,
                frozenset({"chat", "structured_output"}),
                "normalized",
                "",
                {"action": "process", "summary": "hello", "reason": "test"},
                ModelUsage(),
                0.0,
            )
        return ModelResult(
            request.role,
            frozenset({"chat"}),
            "normalized",
            "",
            None,
            ModelUsage(),
            0.0,
            tool_calls=(ToolCall("call-1", "com.vendor.send", {"text": "reply"}),),
            finish_reason="tool_calls",
        )


class _ReceiptToolExecutor:
    def __init__(self, engine: AgentEngine) -> None:
        self.engine = engine

    async def execute_tool(self, request: ToolExecutionRequest) -> None:
        await self.engine.submit_amp(
            tool_receipt_amp(
                status="succeeded",
                request=request,
                summary="replied",
                source_app="test",
                source_instance="local",
                result={"text": "ok"},
            )
        )


class _ToolingRootHandler:
    def handle(self, context: AgentContext) -> AgentDecision:
        if context.message.type == "agent.assigned":
            return AgentDecision(
                tool_request=ToolRequest(
                    capability="com.vendor.send",
                    parameters={"text": "reply"},
                    complete_task=False,
                    tool_call_id="call-1",
                )
            )
        if context.message.type == "tool.succeeded":
            return AgentDecision(completion=Completion("replied"))
        return AgentDecision(completion=Completion("done"))


def test_run_forever_dispatches_background_tool_activities(tmp_path: Path) -> None:
    """run_forever 自旋时后台工具派发不得被饿死：工具活动必须被领取并执行。"""
    calls: list[str] = []

    class RecordingExecutor(_ReceiptToolExecutor):
        async def execute_tool(self, request: ToolExecutionRequest) -> None:
            calls.append(request.capability)
            await super().execute_tool(request)

    async def exercise() -> None:
        triage_profile = AgentProfile(
            id="builtin.triage",
            implementation="unused",
            model_role="test",
            capabilities=frozenset(),
            can_delegate=True,
            child_profiles=frozenset({"builtin.root"}),
            triage_control=True,
        )
        root_profile = AgentProfile(
            id="builtin.root",
            implementation="unused",
            model_role="test",
            capabilities=frozenset({"*"}),
            can_delegate=False,
            child_profiles=frozenset(),
        )
        configuration = EngineConfiguration(
            workspace=str(tmp_path / "engine"),
            profiles=(triage_profile, root_profile),
            limits=AgentLimits(root_profile=triage_profile.id, worker_profile=root_profile.id),
            interactive_budget=TaskLimits(4, 4, 30.0),
            autonomous_budget=TaskLimits(4, 4, 30.0),
            triage=TriageLimits(quiet_seconds=0, max_wait_seconds=0.001),
        )
        engine = AgentEngine(
            configuration,
            {"builtin.triage": TriageAgent(), "builtin.root": _ToolingRootHandler()},
            model_provider=_ToolingModelProvider(),
        )
        engine.bind_tool_executors(
            (
                ToolExecutorBinding(
                    CapabilityDescriptor(
                        "com.vendor.send",
                        "send a message",
                        {"type": "object", "properties": {"text": {"type": "string"}}},
                    ),
                    RecordingExecutor(engine),
                    "test",
                    "local",
                ),
            )
        )
        stop = asyncio.Event()
        loop_task = asyncio.create_task(engine.run_forever(stop), name="runtime-loop")
        try:
            await engine.submit_amp(
                new_amp(
                    event_type="message.received",
                    session_id="test-session",
                    summary="hello",
                    data={"text": "hello"},
                    source_app="test",
                    source_instance="local",
                ).to_dict()
            )
            for _ in range(200):
                await asyncio.sleep(0.05)
                tasks = engine.tasks()
                if tasks and all(task.terminal for task in tasks):
                    break
            assert calls == ["com.vendor.send"], f"tool executor not invoked: {calls}"
            assert all(task.terminal for task in engine.tasks())
        finally:
            stop.set()
            await asyncio.gather(loop_task, return_exceptions=True)
            await engine.shutdown()

    asyncio.run(exercise())
