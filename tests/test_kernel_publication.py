from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

from src.contracts.agent import (
    ActivityStatus,
    AgentContext,
    AgentDecision,
    AgentLimits,
    AgentProfile,
    CapabilityCatalogSnapshot,
    CapabilityDescriptor,
    DelegationRequest,
    DestinationGrant,
    KernelConfiguration,
    PublicationRequest,
    TaskBudget,
    TaskStatus,
)
from src.contracts.amp import AmpEnvelope, new_amp
from src.kernel.runtime import AgentKernel

if TYPE_CHECKING:
    from pathlib import Path


CAPABILITY = "test.chat.publish"
ENDPOINT = "test.chat"
EXPECTED_PUBLICATIONS = 2
PUBLICATION_DESCRIPTOR = CapabilityDescriptor(
    id=CAPABILITY,
    description="Publish test text",
    parameters_schema={
        "type": "object",
        "properties": {"text": {"type": "string", "minLength": 1}},
        "required": ["text"],
        "additionalProperties": False,
    },
    kind="publication",
    endpoint=ENDPOINT,
    operation="reply",
    root_only=True,
)


def configuration(workspace: Path, *, with_worker: bool = False) -> KernelConfiguration:
    gate = AgentProfile(
        "gate",
        "test",
        "fast",
        "gate",
        frozenset({CAPABILITY}),
        can_delegate=with_worker,
        child_profiles=frozenset({"worker"}) if with_worker else frozenset(),
    )
    profiles = [gate]
    if with_worker:
        profiles.append(
            AgentProfile(
                "worker",
                "test",
                "fast",
                "worker",
                frozenset({CAPABILITY}),
                can_delegate=False,
                child_profiles=frozenset(),
            )
        )
    return KernelConfiguration(
        str(workspace),
        "persona",
        "hash",
        tuple(profiles),
        AgentLimits(root_profile="gate", worker_profile="worker" if with_worker else "gate"),
        TaskBudget(8, 6, 300),
        TaskBudget(3, 2, 120),
    )


def communication_amp(*, audience: str = "test.chat:one", route: str = "route-one") -> AmpEnvelope:
    return new_amp(
        event_type="message.received",
        session_id="legacy-session",
        summary=f"message for {audience}",
        data={
            "communication": {
                "endpoint_id": ENDPOINT,
                "external_event_id": str(uuid4()),
                "external_message_id": str(uuid4()),
                "conversation_ref": f"conversation:{audience}",
                "actor_ref": f"actor:{audience}",
                "audience_ref": audience,
                "reply_route_ref": route,
            }
        },
        source_app=ENDPOINT,
        source_instance="test",
    )


def publication_receipt(request_id: str, event_type: str) -> AmpEnvelope:
    return new_amp(
        event_type=event_type,
        session_id="receipt",
        summary=event_type,
        data={
            "request_id": request_id,
            "capability": CAPABILITY,
            "endpoint_id": ENDPOINT,
            "operation": "reply",
            "result": {"external_message_id": str(uuid4())},
        },
        source_app=ENDPOINT,
        source_instance="test",
    )


def install_reply(kernel: AgentKernel) -> None:
    kernel.install_capability_catalog(CapabilityCatalogSnapshot((PUBLICATION_DESCRIPTOR,)))


def test_root_can_publish_twice_then_complete_on_second_success(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            mode = "continue" if context.message.type == "task.started" else "complete_on_success"
            text = "first" if mode == "continue" else "second"
            return AgentDecision(publication_request=PublicationRequest("reply", text, mode, route_ref="route-one"))

    kernel = AgentKernel(configuration(tmp_path), {"gate": Handler()})
    install_reply(kernel)

    async def scenario() -> None:
        await kernel.submit_amp(communication_amp())
        await kernel.pump()
        first = (await kernel.claim_publication_requests())[0]
        assert first.completion_mode == "continue"
        await kernel.submit_amp(publication_receipt(first.request_id, "publication.succeeded"))
        await kernel.pump()
        second = (await kernel.claim_publication_requests())[0]
        assert second.request_id != first.request_id
        assert second.completion_mode == "complete_on_success"
        await kernel.submit_amp(publication_receipt(second.request_id, "publication.succeeded"))
        await kernel.pump()
        task = kernel.tasks()[0]
        assert task.status == TaskStatus.COMPLETED
        assert task.tool_calls == EXPECTED_PUBLICATIONS

    try:
        asyncio.run(scenario())
    finally:
        kernel.shutdown()


def test_child_publication_is_rejected_as_root_only(tmp_path: Path) -> None:
    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            if context.agent.parent_agent_id is None:
                return AgentDecision(delegations=(DelegationRequest("draft", "worker"),))
            return AgentDecision(
                publication_request=PublicationRequest(
                    "reply", "not allowed", "complete_on_success", route_ref="route-one"
                )
            )

    handler = Handler()
    kernel = AgentKernel(configuration(tmp_path, with_worker=True), {"gate": handler, "worker": handler})
    install_reply(kernel)

    async def scenario() -> None:
        await kernel.submit_amp(communication_amp())
        await kernel.pump()
        result = await kernel.pump()
        assert result.failed_message_ids
        child = next(agent for agent in kernel.store.agents() if agent.parent_agent_id is not None)
        assert child.status.value == "FAILED"
        assert kernel.tasks()[0].status == TaskStatus.ACTIVE
        assert not await kernel.claim_publication_requests()

    try:
        asyncio.run(scenario())
    finally:
        kernel.shutdown()


def test_delivery_unknown_restores_root_without_completing(tmp_path: Path) -> None:
    class Handler:
        def handle(self, _context: AgentContext) -> AgentDecision:
            return AgentDecision(
                publication_request=PublicationRequest(
                    "reply", "uncertain", "complete_on_success", route_ref="route-one"
                )
            )

    kernel = AgentKernel(configuration(tmp_path), {"gate": Handler()})
    install_reply(kernel)

    async def scenario() -> None:
        await kernel.submit_amp(communication_amp())
        await kernel.pump()
        lease = (await kernel.claim_publication_requests())[0]
        await kernel.submit_amp(publication_receipt(lease.request_id, "publication.delivery_unknown"))
        kernel.ingest_ready()
        task = kernel.tasks()[0]
        assert task.status == TaskStatus.ACTIVE
        claim = kernel.store.claim_message(30)
        assert claim is not None and claim[0].type == "publication.delivery_unknown"
        with kernel.store.connect() as connection:
            activity = connection.execute(
                "SELECT status, error FROM activities WHERE activity_id = ?", (lease.activity_id,)
            ).fetchone()
        assert activity is not None and activity["status"] == ActivityStatus.ERROR
        assert activity["error"] == "delivery_unknown"

    try:
        asyncio.run(scenario())
    finally:
        kernel.shutdown()


def test_destination_grant_authorizes_operation_and_target_audience(tmp_path: Path) -> None:
    descriptor = CapabilityDescriptor(
        CAPABILITY,
        "Proactive test publication",
        PUBLICATION_DESCRIPTOR.parameters_schema,
        kind="publication",
        endpoint=ENDPOINT,
        operation="proactive_send",
        root_only=True,
    )
    grant = DestinationGrant(
        alias="owner",
        endpoint_id=ENDPOINT,
        capability_id=CAPABILITY,
        operation="proactive_send",
        allowed_source_audiences=frozenset({"system.local"}),
        target_audience_ref="test.chat:owner",
        configuration_hash="sha256:test",
    )

    offered_schema: dict[str, object] = {}

    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            offered_schema.update(context.capabilities[0].parameters_schema)
            return AgentDecision(
                publication_request=PublicationRequest(
                    "proactive_send", "notice", "continue", destination="owner", reason="scheduled"
                )
            )

    kernel = AgentKernel(configuration(tmp_path), {"gate": Handler()}, destination_grants=(grant,))
    kernel.install_capability_catalog(CapabilityCatalogSnapshot((descriptor,)))

    async def scenario() -> None:
        await kernel.submit_amp(
            new_amp(
                event_type="system.tick",
                session_id="system",
                summary="tick",
                data={},
                source_app="aurora",
                source_instance="test",
            )
        )
        await kernel.pump()
        lease = (await kernel.claim_publication_requests())[0]
        assert lease.destination == "owner"
        assert lease.target_audience_ref == "test.chat:owner"
        assert lease.operation == "proactive_send"
        properties = offered_schema["properties"]
        assert isinstance(properties, dict)
        assert properties["destination"]["enum"] == ["owner"]

    try:
        asyncio.run(scenario())
    finally:
        kernel.shutdown()


def test_processing_publication_is_exposed_for_restart_recovery(tmp_path: Path) -> None:
    class Handler:
        def handle(self, _context: AgentContext) -> AgentDecision:
            return AgentDecision(
                publication_request=PublicationRequest("reply", "hello", "continue", route_ref="route-one")
            )

    first = AgentKernel(configuration(tmp_path), {"gate": Handler()})
    install_reply(first)

    async def prepare() -> tuple[str, str]:
        await first.submit_amp(communication_amp())
        await first.pump()
        lease = (await first.claim_publication_requests())[0]
        return lease.activity_id, lease.request_id

    activity_id, request_id = asyncio.run(prepare())
    first.shutdown()
    restarted = AgentKernel(configuration(tmp_path), {"gate": Handler()})
    install_reply(restarted)
    try:
        recoveries = asyncio.run(restarted.publication_recovery_requests())
        assert len(recoveries) == 1
        assert recoveries[0].activity_id == activity_id
        assert recoveries[0].request_id == request_id
        messages = restarted.store.messages_for_agent(recoveries[0].agent_id)
        assert not any(message["type"] == "publication.failed" for message in messages)
    finally:
        restarted.shutdown()


def test_brain_context_hides_cross_audience_content(tmp_path: Path) -> None:
    contexts: dict[str, AgentContext] = {}

    class Handler:
        def handle(self, context: AgentContext) -> AgentDecision:
            contexts[context.task.audience_ref] = context
            return AgentDecision(model_request={"role": "fast"})

    kernel = AgentKernel(configuration(tmp_path), {"gate": Handler()})
    install_reply(kernel)

    async def scenario() -> None:
        await kernel.submit_amp(communication_amp(audience="test.chat:a", route="route-a"))
        await kernel.submit_amp(communication_amp(audience="test.chat:b", route="route-b"))
        await kernel.pump(2)
        context = contexts["test.chat:a"]
        other_task = next(item for item in context.brain.active_tasks if item["task_id"] != context.task.task_id)
        other_agent = next(item for item in context.brain.active_agents if item["task_id"] == other_task["task_id"])
        assert "summary" not in other_task
        assert "latest_activity" not in other_task
        assert "assignment" not in other_agent
        assert "last_summary" not in other_agent

    try:
        asyncio.run(scenario())
    finally:
        kernel.shutdown()
