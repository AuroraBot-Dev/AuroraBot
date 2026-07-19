from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from src.agents.tool_agent import MEMORY_QUERY_TOOL, ToolAgent
from src.contracts.agent import (
    AgentContext,
    AgentDecision,
    AgentLimits,
    AgentProfile,
    CapabilityCatalogSnapshot,
    CapabilityDescriptor,
    Completion,
    DelegationRequest,
    EffectRequest,
    KernelConfiguration,
    TaskBudget,
    TaskStatus,
)
from src.contracts.amp import AmpEnvelope, new_amp
from src.contracts.model import ModelContinuation, ModelResult, ModelUsage, ToolCall
from src.kernel.runtime import AgentKernel

if TYPE_CHECKING:
    from pathlib import Path


def configuration(workspace: Path, profiles: tuple[AgentProfile, ...]) -> KernelConfiguration:
    return KernelConfiguration(
        workspace=str(workspace),
        soul_content="A shared persona",
        soul_hash="hash",
        profiles=profiles,
        limits=AgentLimits(
            root_profile="gate",
            worker_profile="worker",
            max_active_agents=16,
            max_agents_per_task=8,
            max_depth=3,
            max_children_per_agent=4,
        ),
        interactive_budget=TaskBudget(8, 6, 300),
        autonomous_budget=TaskBudget(3, 2, 120),
    )


def profiles() -> tuple[AgentProfile, ...]:
    return (
        AgentProfile(
            "gate",
            "test",
            "fast",
            "gate",
            frozenset({"reply"}),
            can_delegate=True,
            child_profiles=frozenset({"worker"}),
        ),
        AgentProfile(
            "worker",
            "test",
            "agent",
            "worker",
            frozenset({"reply", "clock"}),
            can_delegate=True,
            child_profiles=frozenset({"worker"}),
        ),
    )


def input_amp(message_id: str = "00000000-0000-4000-8000-000000000001") -> AmpEnvelope:
    value = new_amp(
        event_type="message.received",
        session_id="session",
        summary="root task",
        data={},
        source_app="test",
        source_instance="test",
    ).to_dict()
    value["header"]["message_id"] = message_id
    return AmpEnvelope.parse(value)


def test_child_reports_resume_parent_one_by_one(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.agent.parent_agent_id is None and context.message.type == "task.started":
                return AgentDecision(
                    delegations=(DelegationRequest("first"), DelegationRequest("second")),
                )
            if context.agent.parent_agent_id is not None:
                return AgentDecision(completion=Completion(context.agent.assignment))
            completed = int(context.agent.state.get("completed", 0)) + 1
            if completed == 1:
                return AgentDecision(wait_for_children=True, state_patch={"completed": completed})
            return AgentDecision(completion=Completion("all children reported"), state_patch={"completed": completed})

    kernel = AgentKernel(configuration(tmp_path, profiles()), {"gate": Handler(), "worker": Handler()})

    async def scenario() -> None:
        await kernel.submit_amp(input_amp())
        first = await kernel.pump(8)
        assert len(first.processed_message_ids) == 1
        second = await kernel.pump(8)
        assert len(second.processed_message_ids) == 2
        third = await kernel.pump(1)
        assert len(third.processed_message_ids) == 1
        assert kernel.get_task(kernel.tasks()[0].task_id).status == TaskStatus.ACTIVE  # type: ignore[union-attr]
        fourth = await kernel.pump(1)
        assert len(fourth.processed_message_ids) == 1
        assert kernel.tasks()[0].status == TaskStatus.COMPLETED

    asyncio.run(scenario())


def test_child_terminal_effect_is_rejected_but_resume_effect_is_allowed(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.agent.parent_agent_id is None:
                return AgentDecision(delegations=(DelegationRequest("use a tool"),))
            capability = "reply" if context.message.type == "agent.assigned" else "clock"
            return AgentDecision(effect_request=EffectRequest(capability, {"text": "hello"}))

    kernel = AgentKernel(configuration(tmp_path, profiles()), {"gate": Handler(), "worker": Handler()})
    kernel.install_capability_catalog(
        CapabilityCatalogSnapshot(
            (
                CapabilityDescriptor(
                    "reply",
                    "terminal reply",
                    {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                    "terminal",
                ),
                CapabilityDescriptor(
                    "clock",
                    "resume tool",
                    {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                    "resume",
                ),
            )
        )
    )

    async def scenario() -> None:
        await kernel.submit_amp(input_amp())
        await kernel.pump()
        rejected = await kernel.pump()
        assert rejected.failed_message_ids
        child = next(agent for agent in kernel.store.agents() if agent.parent_agent_id is not None)
        assert child.status.value == "FAILED"

    asyncio.run(scenario())


def test_terminal_effect_receipt_completes_root_task_once(tmp_path: Path) -> None:
    class Handler:
        def handle(self, _context: AgentContext) -> AgentDecision:
            return AgentDecision(effect_request=EffectRequest("reply", {"text": "hello"}))

    gate = AgentProfile(
        "gate",
        "test",
        "fast",
        "gate",
        frozenset({"reply"}),
        can_delegate=False,
        child_profiles=frozenset(),
    )
    config = configuration(tmp_path, (gate, profiles()[1]))
    kernel = AgentKernel(config, {"gate": Handler(), "worker": Handler()})
    kernel.install_capability_catalog(
        CapabilityCatalogSnapshot(
            (
                CapabilityDescriptor(
                    "reply",
                    "terminal reply",
                    {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                    "terminal",
                ),
            )
        )
    )

    async def scenario() -> None:
        await kernel.submit_amp(input_amp())
        await kernel.pump()
        lease = (await kernel.claim_effect_requests())[0]
        receipt = new_amp(
            event_type="effect.succeeded",
            session_id="session",
            summary="delivered",
            data={
                "request_id": lease.request_id,
                "capability": "reply",
                "result": {"ok": True},
            },
            source_app="platform.test",
            source_instance="test",
        )
        await kernel.submit_amp(receipt)
        await kernel.pump()
        assert kernel.tasks()[0].status == TaskStatus.COMPLETED
        await kernel.submit_amp(receipt)
        await kernel.pump()
        assert len(kernel.tasks()) == 1

    asyncio.run(scenario())


def test_brain_context_is_runtime_owned_global_projection(tmp_path: Path) -> None:
    class Handler:
        def handle(self, _context: AgentContext) -> AgentDecision:
            return AgentDecision(model_request={"role": "fast"})

    gate, worker = profiles()
    kernel = AgentKernel(configuration(tmp_path, (gate, worker)), {"gate": Handler(), "worker": Handler()})
    kernel.store.add_situation("clock", "clock.alarm", "wake up", {"ambient": True}, 10, 1800)

    async def scenario() -> None:
        await kernel.submit_amp(input_amp())
        await kernel.pump()
        snapshot = kernel.brain_context()
        assert snapshot.persona["content"] == "A shared persona"
        assert snapshot.active_tasks[0]["summary"] == "root task"
        assert snapshot.active_agents
        assert snapshot.ambient_situations[0]["summary"] == "wake up"

    asyncio.run(scenario())


def test_unconfigured_memory_agent_returns_nonfatal_tool_result(tmp_path: Path) -> None:
    gate, worker = profiles()
    kernel = AgentKernel(configuration(tmp_path, (gate, worker)), {"gate": ToolAgent(), "worker": ToolAgent()})

    async def scenario() -> None:
        await kernel.submit_amp(input_amp())
        await kernel.pump()
        first_activity = (await kernel.claim_model_requests(1))[0]
        result = ModelResult(
            model="test",
            negotiated_capabilities=frozenset({"chat", "tools"}),
            response_mode="normalized",
            text="",
            data=None,
            usage=ModelUsage(),
            cost_usd=0,
            tool_calls=(ToolCall("memory-call", MEMORY_QUERY_TOOL, {"query": "who am I?"}),),
            finish_reason="tool_calls",
            continuation=ModelContinuation("test", "chat_completions", ()),
        )
        await kernel.complete_model(first_activity, result.to_dict(), None)
        resumed = await kernel.pump()
        assert resumed.failed_message_ids == ()
        second_activity = (await kernel.claim_model_requests(1))[0]
        continuation = second_activity.request["continuation"]
        tool_output = json.loads(continuation["items"][-1]["content"])
        assert tool_output["result"]["code"] == "memory.unavailable"
        assert tool_output["result"]["ok"] is False

    asyncio.run(scenario())
