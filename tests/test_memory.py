# ruff: noqa: PLR2004
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

from src.agents.capabilities.memory import MemoryCapability
from src.contracts import (
    MEMORY_REMEMBER_CAPABILITY,
    AgentDecision,
    MemoryEntry,
    MemoryQuery,
    ToolCall,
    ToolExecutionRequest,
)
from src.engine.authorize import _capability_allowed
from src.memory.executor import MEMORY_REMEMBER_DESCRIPTOR, MemoryToolExecutor
from src.memory.service import MemoryService

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.agent import AgentContext


def test_service_without_memory_dir_falls_back_to_empty_context() -> None:
    async def exercise() -> None:
        service = MemoryService()
        recalled = await service.recall(MemoryQuery("anything", "session"))
        assert recalled.summary == ""
        assert recalled.window == ()
        assert not await service.remember(MemoryEntry("task", "session", "hello", "hi", "2026-01-01"))

    asyncio.run(exercise())


def test_window_bounds_and_natural_forgetting(tmp_path: Path) -> None:
    """上下界批量压缩；压缩项被再次浓缩（自然遗忘）。"""

    async def exercise() -> None:
        service = MemoryService(tmp_path, window_min=2, window_max=4)
        for index in range(1, 9):
            await service.append_turn("session", role="user", content=f"question {index}", at=f"2026-01-0{index}")

        recalled = await service.recall(MemoryQuery("", "session"))
        # 窗口压缩回下界 2 条
        assert [message.content for message in recalled.window] == ["question 7", "question 8"]
        # 概要第一段为最早记忆的压缩项（含 question 1 的事实），随后分段
        assert "question 1" in recalled.summary
        # 首次压缩把最早的对话浓缩为第一段；后续压缩再次浓缩第一段（每次压缩重复处理）
        assert recalled.summary.count("question 1") >= 1
        assert "question 4" in recalled.summary or "question 5" in recalled.summary

    asyncio.run(exercise())


def test_memory_is_idempotent_session_scoped_and_fact_bounded(tmp_path: Path) -> None:
    service = MemoryService(tmp_path)
    first = MemoryEntry(
        "task-1",
        "session",
        "用户：first question",
        "first answer",
        "2026-01-01",
        ("user prefers concise answers",),
    )
    duplicate = MemoryEntry("task-1", "session", "changed", "changed", "2026-01-03")
    other = MemoryEntry("task-3", "other", "用户：other", "other answer", "2026-01-04")

    async def exercise() -> None:
        assert await service.remember(first)
        assert not await service.remember(duplicate)
        assert await service.remember(other)

        recalled = await service.recall(MemoryQuery("concise", "session", fact_limit=1))
        assert "other answer" not in recalled.summary
        assert recalled.relevant_facts == ("user prefers concise answers",)

    asyncio.run(exercise())


def test_memory_snapshot_obeys_total_character_budget(tmp_path: Path) -> None:
    async def exercise() -> None:
        service = MemoryService(tmp_path, window_min=1, window_max=2)
        await service.append_turn("session", role="user", content="x" * 100, at="2026-01-01")
        await service.append_turn("session", role="assistant", content="y" * 100, at="2026-01-02")
        recalled = await service.recall(MemoryQuery("query", "session", max_characters=32))
        total = (
            len(recalled.summary)
            + sum(len(message.content) for message in recalled.window)
            + sum(map(len, recalled.relevant_facts))
        )
        assert total <= 32
        assert [message.content for message in recalled.window] == ["y" * 31 + "…"]

    asyncio.run(exercise())


def test_window_condensation_awaits_async_summarizer(tmp_path: Path) -> None:
    calls: list[list[dict[str, object]]] = []

    class Gateway:
        async def get_response(self, role: str, inputs: list[dict]) -> dict[str, Any]:
            assert role == "fast"
            assert asyncio.get_running_loop().is_running()
            calls.append(inputs)
            return {"text": "LLM 生成的会话概要"}

    async def exercise() -> None:
        service = MemoryService(tmp_path, gateway=Gateway(), window_min=1, window_max=2)
        for index in range(3):
            await service.append_turn("session", role="user", content=f"message {index}", at=str(index))
        recalled = await service.recall(MemoryQuery("", "session"))
        assert recalled.summary == "LLM 生成的会话概要"
        assert [message.content for message in recalled.window] == ["message 2"]

    asyncio.run(exercise())
    assert len(calls) == 1


def test_semantic_recall_precedes_and_falls_back_to_durable_facts(tmp_path: Path) -> None:
    class LongTerm:
        result: tuple[str, ...] = ("semantic preference",)

        def add(self, scope: str, text: str, at: str) -> None:  # noqa: ARG002
            return None

        def search(self, scope: str, query: str, limit: int) -> tuple[str, ...]:  # noqa: ARG002
            return self.result[:limit]

        def status(self) -> dict[str, object]:
            return {"enabled": True, "degraded": False, "reason": None}

    async def exercise() -> None:
        service = MemoryService(tmp_path)
        long_term = LongTerm()
        service._long_term = cast("Any", long_term)
        await service.remember(
            MemoryEntry("task", "session", "question", "answer", "2026-01-01", ("keyword preference",))
        )

        semantic = await service.recall(MemoryQuery("preference", "session", fact_limit=2))
        assert semantic.relevant_facts == ("semantic preference", "keyword preference")

        long_term.result = ()
        fallback = await service.recall(MemoryQuery("keyword", "session", fact_limit=2))
        assert fallback.relevant_facts == ("keyword preference",)

    asyncio.run(exercise())


class _ReceiptIngress:
    """捕获回执 AMP 的假入口。"""

    def __init__(self) -> None:
        self.amps: list[dict[str, object]] = []

    async def submit_amp(self, value: object) -> str:
        self.amps.append(value)  # type: ignore[arg-type]
        return ""


def _receipt_of(amp: dict[str, object]) -> dict[str, object]:
    payload = amp["payload"]
    assert isinstance(payload, dict)
    return {"type": payload.get("type"), "data": payload.get("data")}


def test_executor_writes_memory_and_submits_receipt(tmp_path: Path) -> None:
    service = MemoryService(tmp_path)
    ingress = _ReceiptIngress()
    executor = MemoryToolExecutor(service, ingress)  # type: ignore[arg-type]
    request = ToolExecutionRequest(
        "request-1",
        "session",
        MEMORY_REMEMBER_CAPABILITY,
        {"content": "记住：用户偏好简洁回答", "fact_candidates": ["用户偏好简洁回答"]},
    )
    asyncio.run(executor.execute_tool(request))
    assert _receipt_of(ingress.amps[0])["type"] == "tool.succeeded"
    recalled = asyncio.run(service.recall(MemoryQuery("简洁", "session", fact_limit=4)))
    assert "用户偏好简洁回答" in recalled.relevant_facts


def test_executor_submits_failed_receipt_for_missing_content(tmp_path: Path) -> None:
    ingress = _ReceiptIngress()
    executor = MemoryToolExecutor(MemoryService(tmp_path), ingress)  # type: ignore[arg-type]
    asyncio.run(
        executor.execute_tool(
            ToolExecutionRequest("request-1", "session", MEMORY_REMEMBER_CAPABILITY, {"content": "  "})
        )
    )
    receipt = _receipt_of(ingress.amps[0])
    assert receipt["type"] == "tool.failed"
    data = receipt["data"]
    assert isinstance(data, dict) and data.get("error") is not None


def test_capability_builds_tool_request_and_validates() -> None:
    capability = MemoryCapability()
    assert capability.tool_names == frozenset({MEMORY_REMEMBER_CAPABILITY})
    assert capability.tool_definitions(cast("AgentContext", object())) == ()
    decision = capability.handle_tool(
        ToolCall("call-1", MEMORY_REMEMBER_CAPABILITY, {"content": "记住 X", "fact_candidates": ["X"]})
    )
    assert decision is not None and decision.tool_request is not None
    assert decision.tool_request.parameters == {"content": "记住 X", "fact_candidates": ["X"]}
    rejected = capability.handle_tool(ToolCall("call-2", MEMORY_REMEMBER_CAPABILITY, {}))
    assert rejected is not None and rejected.failure is not None
    without_facts = capability.handle_tool(ToolCall("call-3", MEMORY_REMEMBER_CAPABILITY, {"content": "记住 Y"}))
    assert without_facts is not None and without_facts.tool_request is not None
    assert without_facts.tool_request.parameters == {"content": "记住 Y"}


def test_memory_descriptor_schema_requires_content() -> None:
    assert MEMORY_REMEMBER_DESCRIPTOR.id == MEMORY_REMEMBER_CAPABILITY
    assert MEMORY_REMEMBER_DESCRIPTOR.parameters_schema["required"] == ["content"]


def test_capability_allowed_exclusion_overrides_wildcard() -> None:
    allowed = frozenset({"*", "!aur.serv.memory.remember"})
    assert _capability_allowed("aur.mcp.org.aurora.clock.get_time", allowed)
    assert _capability_allowed("aur.mcp.org.aurora.clock.get_time", allowed)
    assert not _capability_allowed(MEMORY_REMEMBER_CAPABILITY, allowed)
    assert _capability_allowed(MEMORY_REMEMBER_CAPABILITY, frozenset({MEMORY_REMEMBER_CAPABILITY}))


def test_memory_agent_full_chain_delegation_writes_same_store(tmp_path: Path) -> None:
    """全链路：本体意识委派记忆 agent → 工具请求 → executor 写入同一 SQLite。"""
    from src.agents.capabilities import DelegationCapability, MemoryCapability
    from src.agents.handler import ToolAgent
    from src.agents.triage import TriageAgent
    from src.contracts import (
        AgentLimits,
        AgentProfile,
        DelegationRequest,
        EngineConfiguration,
        TaskLimits,
        ToolExecutorBinding,
        TriageLimits,
        new_amp,
    )
    from src.engine.runtime import AgentEngine
    from src.prompt import PromptCatalog, PromptComposer
    from tests.support import TriageModelProvider

    memory = MemoryService(tmp_path / "memory")
    catalog = PromptCatalog.create(
        soul="soul", world="world", agents={"gate": "gate", "memory": "memory", "worker": "worker"}
    )
    capabilities = (DelegationCapability(), MemoryCapability())
    composer = PromptComposer(catalog)
    gate = ToolAgent(composer=composer, capabilities=capabilities)
    memory_agent = ToolAgent(composer=composer, capabilities=capabilities)

    class GateHandler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.message.type == "agent.assigned" and not context.children:
                return AgentDecision(delegations=(DelegationRequest("记住：用户偏好简洁", "memory"),))
            return gate.handle(context)

    class MemoryHandler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.message.type == "agent.assigned":
                decision = MemoryCapability().handle_tool(
                    ToolCall("memory-call", MEMORY_REMEMBER_CAPABILITY, {"content": "用户偏好简洁"})
                )
                assert decision is not None
                return decision
            return memory_agent.handle(context)

    profiles = (
        AgentProfile(
            "triage",
            "test",
            "fast",
            frozenset(),
            can_delegate=True,
            child_profiles=frozenset({"gate"}),
            triage_control=True,
        ),
        AgentProfile(
            "gate",
            "test",
            "quality",
            frozenset({"*", "!aurora.memory.remember"}),
            can_delegate=True,
            child_profiles=frozenset({"worker", "memory"}),
        ),
        AgentProfile(
            "worker",
            "test",
            "quality",
            frozenset({"*", "!aurora.memory.remember"}),
            can_delegate=True,
            child_profiles=frozenset({"worker"}),
        ),
        AgentProfile(
            "memory",
            "test",
            "quality",
            frozenset({MEMORY_REMEMBER_CAPABILITY}),
            can_delegate=False,
            child_profiles=frozenset(),
        ),
    )
    configuration = EngineConfiguration(
        str(tmp_path / "engine"),
        profiles,
        AgentLimits(root_profile="triage", worker_profile="worker"),
        TaskLimits(8, 8, 300),
        TaskLimits(8, 8, 120),
        TriageLimits(quiet_seconds=0, max_wait_seconds=0.001),
    )
    engine = AgentEngine(
        configuration,
        {"triage": TriageAgent(), "gate": GateHandler(), "worker": gate, "memory": MemoryHandler()},
        model_provider=TriageModelProvider(),
        memory_store=memory,
    )
    engine.bind_tool_executors(
        (ToolExecutorBinding(MEMORY_REMEMBER_DESCRIPTOR, MemoryToolExecutor(memory, engine), "memory", "local"),)
    )

    async def scenario() -> None:
        await engine.submit_amp(
            new_amp(
                event_type="message.received",
                session_id="session",
                summary="hello",
                data={"text": "hello"},
                source_app="test",
                source_instance="local",
            ).to_dict()
        )
        await asyncio.sleep(0.001)
        result = await engine.pump()
        task_id = result["admitted_task_ids"][0]
        for _ in range(16):
            detail = engine.task_detail(task_id)
            if detail is None or detail["task"]["status"] != "ACTIVE":
                break
            await engine.pump()
            await asyncio.sleep(0)  # 让模型派发与记忆投影任务执行

        # 记忆 agent 完成后，主动写入应已落库（同源 SQLite）
        await asyncio.sleep(0)
        recalled = await memory.recall(MemoryQuery("简洁", "session", fact_limit=4))
        assert any("用户偏好简洁" in item.content for item in recalled.window)

    try:
        asyncio.run(scenario())
    finally:
        asyncio.run(engine.shutdown())
