from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

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
    KernelConfiguration,
    TaskBudget,
    TaskStatus,
    ToolRequest,
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


def test_child_uses_package_wildcard_capability(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.agent.parent_agent_id is None:
                return AgentDecision(delegations=(DelegationRequest("use a tool"),))
            return AgentDecision(tool_request=ToolRequest("test.reply", {"text": "hello"}))

    gate, worker = profiles()
    wildcard_worker = AgentProfile(
        worker.id,
        worker.implementation,
        worker.model_role,
        worker.prompt,
        frozenset({"test.*"}),
        worker.can_delegate,
        worker.child_profiles,
    )
    kernel = AgentKernel(configuration(tmp_path, (gate, wildcard_worker)), {"gate": Handler(), "worker": Handler()})
    kernel.install_capability_catalog(
        CapabilityCatalogSnapshot(
            (
                CapabilityDescriptor(
                    "test.reply",
                    "ordinary Tool",
                    {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                ),
            )
        )
    )

    async def scenario() -> None:
        await kernel.submit_amp(input_amp())
        await kernel.pump()
        accepted = await kernel.pump()
        assert accepted.failed_message_ids == ()
        child = next(agent for agent in kernel.store.agents() if agent.parent_agent_id is not None)
        assert child.status.value == "WAITING_TOOL"

    asyncio.run(scenario())


def test_tool_success_restores_root_before_explicit_completion(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.message.type == "tool.succeeded":
                return AgentDecision(completion=Completion("Tool handled"))
            return AgentDecision(tool_request=ToolRequest("reply", {"text": "hello"}))

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
                    "ordinary effect",
                    {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                ),
            )
        )
    )

    async def scenario() -> None:
        await kernel.submit_amp(input_amp())
        await kernel.pump()
        lease = (await kernel.claim_tool_requests())[0]
        await kernel.complete_tool(
            request_id=lease.request_id,
            capability="reply",
            status="succeeded",
            summary="delivered",
            result={"ok": True},
            error=None,
            source_app="platform.test",
            source_instance="test",
        )
        assert kernel.tasks()[0].status == TaskStatus.ACTIVE
        assert any(
            message["type"] == "tool.succeeded"
            for message in kernel.store.messages_for_agent(kernel.tasks()[0].root_agent_id)
        )
        await kernel.pump()
        assert kernel.tasks()[0].status == TaskStatus.COMPLETED
        await kernel.complete_tool(
            request_id=lease.request_id,
            capability="reply",
            status="succeeded",
            summary="delivered",
            result={"ok": True},
            error=None,
            source_app="platform.test",
            source_instance="test",
        )
        await kernel.pump()
        assert len(kernel.tasks()) == 1
        with pytest.raises(ValueError, match="invalid Tool outcome"):
            await kernel.complete_tool(
                request_id=lease.request_id,
                capability="reply",
                status="forged",
                summary="invalid",
                result=None,
                error=None,
                source_app="test",
                source_instance="test",
            )

    asyncio.run(scenario())


def test_succeeded_complete_tool_finishes_root_task(tmp_path: Path) -> None:
    class Handler:
        def handle(self, _context: AgentContext) -> AgentDecision:
            return AgentDecision(tool_request=ToolRequest("reply", {"text": "done"}, complete_task=True))

    gate, worker = profiles()
    kernel = AgentKernel(configuration(tmp_path, (gate, worker)), {"gate": Handler(), "worker": Handler()})
    kernel.install_capability_catalog(
        CapabilityCatalogSnapshot((CapabilityDescriptor("reply", "reply", {"type": "object"}),))
    )

    async def scenario() -> None:
        await kernel.submit_amp(input_amp())
        await kernel.pump()
        lease = (await kernel.claim_tool_requests())[0]
        await kernel.complete_tool(
            request_id=lease.request_id,
            capability=lease.capability,
            status="succeeded",
            summary="delivered",
            result={},
            error=None,
            source_app="test",
            source_instance="test",
        )
        assert kernel.tasks()[0].status == TaskStatus.COMPLETED

    asyncio.run(scenario())


def test_succeeded_complete_tool_finishes_child_and_reports_parent(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.agent.parent_agent_id is None:
                return AgentDecision(delegations=(DelegationRequest("send"),))
            return AgentDecision(tool_request=ToolRequest("reply", {"text": "done"}, complete_task=True))

    gate, worker = profiles()
    kernel = AgentKernel(configuration(tmp_path, (gate, worker)), {"gate": Handler(), "worker": Handler()})
    kernel.install_capability_catalog(
        CapabilityCatalogSnapshot((CapabilityDescriptor("reply", "reply", {"type": "object"}),))
    )

    async def scenario() -> None:
        await kernel.submit_amp(input_amp())
        await kernel.pump()
        await kernel.pump()
        lease = (await kernel.claim_tool_requests())[0]
        await kernel.complete_tool(
            request_id=lease.request_id,
            capability=lease.capability,
            status="succeeded",
            summary="child delivered",
            result={},
            error=None,
            source_app="test",
            source_instance="test",
        )
        child = kernel.get_agent(lease.agent_id)
        assert child is not None and child.status.value == "COMPLETED"
        assert kernel.tasks()[0].status == TaskStatus.ACTIVE
        parent_messages = kernel.store.messages_for_agent(kernel.tasks()[0].root_agent_id)
        assert any(message["type"] == "child.completed" for message in parent_messages)

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


def test_tool_agent_reserves_complete_task_and_starts_new_turn_without_continuation(tmp_path: Path) -> None:
    gate = AgentProfile(
        id="gate",
        implementation="test",
        model_role="fast",
        prompt="gate",
        capabilities=frozenset({"tools.*"}),
        can_delegate=False,
        child_profiles=frozenset(),
    )
    worker = profiles()[1]
    kernel = AgentKernel(configuration(tmp_path, (gate, worker)), {"gate": ToolAgent(), "worker": ToolAgent()})
    descriptor = CapabilityDescriptor(
        "tools.echo",
        "echo",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )
    kernel.install_capability_catalog(CapabilityCatalogSnapshot((descriptor,)))

    async def scenario() -> None:
        await kernel.submit_amp(input_amp())
        await kernel.pump()
        model = (await kernel.claim_model_requests(1))[0]
        schema = next(item for item in model.request["tools"] if item["name"] == "tools.echo")["parameters_schema"]
        assert schema["properties"]["complete_task"]["default"] is False
        result = ModelResult(
            model="test",
            negotiated_capabilities=frozenset({"chat", "tools"}),
            response_mode="normalized",
            text="",
            data=None,
            usage=ModelUsage(),
            cost_usd=0,
            tool_calls=(ToolCall("call", "tools.echo", {"text": "hello", "complete_task": False}),),
            finish_reason="tool_calls",
            continuation=None,
        )
        await kernel.complete_model(model, result.to_dict(), None)
        await kernel.pump()
        lease = (await kernel.claim_tool_requests())[0]
        assert lease.parameters == {"text": "hello"}
        await kernel.complete_tool(
            request_id=lease.request_id,
            capability=lease.capability,
            status="succeeded",
            summary="echoed",
            result={},
            error=None,
            source_app="test",
            source_instance="test",
        )
        await kernel.pump()
        resumed = (await kernel.claim_model_requests(1))[0]
        assert resumed.request["continuation"] is None
        assert resumed.request["messages"]

    asyncio.run(scenario())


def test_tool_agent_preserves_third_party_complete_task_parameter(tmp_path: Path) -> None:
    gate = AgentProfile(
        id="gate",
        implementation="test",
        model_role="fast",
        prompt="gate",
        capabilities=frozenset({"tools.*"}),
        can_delegate=False,
        child_profiles=frozenset(),
    )
    worker = profiles()[1]
    kernel = AgentKernel(configuration(tmp_path, (gate, worker)), {"gate": ToolAgent(), "worker": ToolAgent()})
    raw_schema = {
        "type": "object",
        "properties": {"complete_task": {"type": "string", "enum": ["vendor-value"]}},
        "required": ["complete_task"],
        "additionalProperties": False,
    }
    descriptor = CapabilityDescriptor("tools.vendor", "vendor", raw_schema)
    kernel.install_capability_catalog(CapabilityCatalogSnapshot((descriptor,)))

    async def scenario() -> None:
        await kernel.submit_amp(input_amp())
        await kernel.pump()
        model = (await kernel.claim_model_requests(1))[0]
        tool = next(item for item in model.request["tools"] if item["name"] == "tools.vendor")
        assert tool["parameters_schema"] == raw_schema
        result = ModelResult(
            model="test",
            negotiated_capabilities=frozenset({"chat", "tools"}),
            response_mode="normalized",
            text="",
            data=None,
            usage=ModelUsage(),
            cost_usd=0,
            tool_calls=(ToolCall("call", "tools.vendor", {"complete_task": "vendor-value"}),),
            finish_reason="tool_calls",
            continuation=None,
        )
        await kernel.complete_model(model, result.to_dict(), None)
        await kernel.pump()
        lease = (await kernel.claim_tool_requests())[0]
        assert lease.parameters == {"complete_task": "vendor-value"}
        with kernel.store.connect() as connection:
            request = json.loads(
                connection.execute(
                    "SELECT request_json FROM activities WHERE activity_id = ?", (lease.activity_id,)
                ).fetchone()[0]
            )
        assert request["complete_task"] is False

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "schema",
    [
        {
            "$ref": "#/$defs/input",
            "$defs": {"input": {"type": "object", "properties": {"complete_task": {"type": "string"}}}},
        },
        {"allOf": [{"type": "object", "properties": {"complete_task": {"type": "integer"}}}]},
        {"type": "object", "patternProperties": {"^complete_.*$": {"type": "string"}}},
    ],
)
def test_tool_agent_does_not_override_composed_vendor_complete_task(schema: dict[str, object]) -> None:
    descriptor = CapabilityDescriptor("tools.vendor", "vendor", schema)
    assert ToolAgent._capability_tool(descriptor).parameters_schema == schema
