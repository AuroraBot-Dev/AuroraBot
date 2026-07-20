from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import TYPE_CHECKING

from src.contracts.amp import AmpEnvelope
from src.contracts.configuration import load_configuration
from src.kernel.publication import source_allowed
from src.localhost.ports import PublicationExecutionRequest
from src.localhost.runtime import AuroraRuntime
from src.platform.mcp import MCPPlatform
from src.platform.mcp.communication import RAW_PUBLICATION_SCHEMA
from src.platform.mcp.publication import MCPPublicationService
from src.platform.mcp.publication_ledger import MCPPublicationLedger

if TYPE_CHECKING:
    from pathlib import Path

EXPECTED_QUARANTINES = 2


def _write_communication_apps(project_root: Path) -> None:
    (project_root / "config" / "apps.toml").write_text(
        """[[app]]
package = "com.example.qq"
kind = "communication"
enabled = true
transport = "stdio"
working_dir = "."
command = ["python", "qq.py"]
timeout_seconds = 30

[[app.tool]]
name = "com.example.qq.publish"
kind = "publication"

[[app.publication]]
capability = "com.example.qq.reply"
tool = "com.example.qq.publish"
operation = "reply"

[[app]]
package = "com.example.discord"
kind = "communication"
enabled = true
transport = "stdio"
working_dir = "."
command = ["python", "discord.py"]
timeout_seconds = 30

[[app.tool]]
name = "com.example.discord.publish"
kind = "publication"

[[app.tool]]
name = "com.example.discord.inspect"
kind = "effect"

[[app.publication]]
capability = "com.example.discord.reply"
tool = "com.example.discord.publish"
operation = "reply"

[[app.publication]]
capability = "com.example.discord.relay"
tool = "com.example.discord.publish"
operation = "relay"

[[app.destination]]
alias = "discord.dev"
description = "Discord development channel"
capability = "com.example.discord.relay"
address_ref = "channel:private-configured-id"
allowed_source_audiences = ["com.example.qq:*"]
target_audience_ref = "com.example.discord:dev"
""",
        encoding="utf-8",
    )


def _request(
    configuration_hash: str, *, request_id: str = "delivery-1", text: str = "accepted"
) -> PublicationExecutionRequest:
    return PublicationExecutionRequest(
        request_id=request_id,
        capability="com.example.discord.relay",
        endpoint_id="com.example.discord",
        operation="relay",
        text=text,
        source_audience_ref="com.example.qq:conversation-one",
        target_audience_ref="com.example.discord:dev",
        root_message_id="root-message",
        destination="discord.dev",
        source_endpoint_id="com.example.qq",
        source_external_event_id="qq-event-1",
        hop_count=1,
        configuration_hash=configuration_hash,
    )


@dataclass(slots=True)
class _Ingress:
    values: list[object] = field(default_factory=list)

    async def submit_amp(self, value: object) -> str:
        self.values.append(value)
        return AmpEnvelope.parse(value).header.message_id


def _notification(
    *, external_event_id: str, external_message_id: str, authored_by_self: bool, origin_delivery_id: str | None
) -> dict[str, object]:
    return {
        "type": "message.received",
        "external_event_id": external_event_id,
        "external_message_id": external_message_id,
        "conversation_ref": "conversation-private-ref",
        "actor_ref": "actor-private-ref",
        "reply_route_ref": "reply-route-private-ref",
        "authored_by_self": authored_by_self,
        "origin_delivery_id": origin_delivery_id,
        "summary": "New message",
        "data": {"text": "hello"},
    }


def test_runtime_installs_public_cross_app_destination_grant(project_root: Path) -> None:
    _write_communication_apps(project_root)
    configuration = load_configuration(project_root)
    runtime = AuroraRuntime.create(project_root, configuration=configuration, executor_bindings=None)
    try:
        grant = runtime.kernel._destination_grants["discord.dev"]
        assert grant.endpoint_id == "com.example.discord"
        assert grant.configuration_hash == configuration.apps_configuration_hash
        assert source_allowed(grant, "com.example.qq:conversation-one")
        assert not source_allowed(grant, "com.example.telegram:conversation-one")
        assert "address_ref" not in grant.to_dict()
    finally:
        asyncio.run(runtime.shutdown())


def test_mcp_discovery_splits_effect_and_synthetic_publication_catalogs(project_root: Path) -> None:
    _write_communication_apps(project_root)
    configuration = load_configuration(project_root)
    tools = {
        app.package: [
            SimpleNamespace(
                name=tool.name,
                description=f"Tool {tool.name}",
                inputSchema=RAW_PUBLICATION_SCHEMA if tool.kind == "publication" else {"type": "object"},
            )
            for tool in app.tools
        ]
        for app in configuration.apps
    }

    class FakeKit:
        async def start_all(self, _specs: object) -> None:
            pass

        async def stop_all(self) -> None:
            pass

    class FakeClients:
        notification_queue: asyncio.Queue[tuple[str, str, dict[str, object]]] = asyncio.Queue()

        async def connect_all(self) -> None:
            pass

        async def refresh_tools(self) -> None:
            pass

        def list_all_tools(self) -> dict[str, list[object]]:
            return tools

        async def shutdown(self) -> None:
            pass

    async def scenario() -> None:
        platform = MCPPlatform(configuration)
        platform._kit = FakeKit()  # type: ignore[assignment]
        platform._clients = FakeClients()  # type: ignore[assignment]
        ledger_path = project_root / "data" / "platform" / "mcp" / "publications.sqlite3"
        assert not ledger_path.exists()
        await platform.start(_Ingress())
        try:
            assert {item.id for item in platform.effect_catalog.capabilities} == {"com.example.discord.inspect"}
            assert {item.id for item in platform.publication_catalog.capabilities} == {
                "com.example.qq.reply",
                "com.example.discord.reply",
                "com.example.discord.relay",
            }
            assert "com.example.discord.publish" not in platform.capability_catalog.by_id
            relay = platform.publication_catalog.by_id["com.example.discord.relay"]
            assert relay.endpoint == "com.example.discord" and relay.operation == "relay" and relay.root_only
            assert ledger_path.exists()
        finally:
            await platform.shutdown()

    asyncio.run(scenario())


def test_mcp_publication_three_states_recovery_and_idempotency(project_root: Path) -> None:
    _write_communication_apps(project_root)
    configuration = load_configuration(project_root)
    ledger = MCPPublicationLedger(project_root / "publication-test.sqlite3")
    calls: list[dict[str, object]] = []

    async def call_tool(_tool: str, arguments: dict[str, object]) -> dict[str, object]:
        calls.append(arguments)
        if arguments["text"] == "failed":
            return {"is_error": True, "text": "connector rejected"}
        if arguments["text"] == "unknown":
            raise TimeoutError
        return {
            "status": "accepted",
            "delivery_id": arguments["delivery_id"],
            "external_message_id": f"external-{arguments['delivery_id']}",
        }

    service = MCPPublicationService(configuration, ledger, call_tool)

    async def scenario() -> None:
        accepted_request = _request(configuration.apps_configuration_hash)
        accepted = await service.execute(accepted_request)
        replay = await service.execute(accepted_request)
        conflict = await service.execute(replace(accepted_request, text="different"))
        failed_request = _request(configuration.apps_configuration_hash, request_id="delivery-2", text="failed")
        failed = await service.execute(failed_request)
        unknown_request = _request(configuration.apps_configuration_hash, request_id="delivery-3", text="unknown")
        unknown = await service.execute(unknown_request)

        assert accepted.status == replay.status == "accepted"
        assert accepted.external_message_id == replay.external_message_id == "external-delivery-1"
        assert conflict.status == "failed" and "different request" in (conflict.error or "")
        assert failed.status == "failed" and "connector rejected" in (failed.error or "")
        assert unknown.status == "delivery_unknown"
        assert (await service.recover(accepted_request)).status == "accepted"
        stale_recovery = await service.recover(
            replace(accepted_request, capability="removed.capability", configuration_hash="old-snapshot")
        )
        assert stale_recovery.status == "accepted"
        assert (await service.recover(failed_request)).status == "failed"
        assert (await service.recover(unknown_request)).status == "delivery_unknown"
        missing = await service.recover(replace(unknown_request, request_id="not-dispatched"))
        assert missing.status == "failed" and missing.error == "interrupted_before_dispatch"
        assert len([call for call in calls if call["delivery_id"] == "delivery-1"]) == 1
        raw = calls[0]
        assert raw["operation"] == "relay"
        assert raw["route_ref"] is None
        assert raw["address_ref"] == "channel:private-configured-id"
        assert raw["delivery_id"] == "delivery-1"
        assert raw["provenance"] == {
            "source_endpoint_id": "com.example.qq",
            "source_external_event_id": "qq-event-1",
            "source_audience_ref": "com.example.qq:conversation-one",
            "destination_endpoint_id": "com.example.discord",
            "target_audience_ref": "com.example.discord:dev",
            "hop_count": 1,
        }
        columns = {row["name"] for row in ledger._database.execute("PRAGMA table_info(publications)").fetchall()}
        assert "address_ref" not in columns and "route_ref" not in columns and "token" not in columns

        same_audience = replace(
            _request(configuration.apps_configuration_hash, request_id="delivery-loop"),
            source_audience_ref="com.example.discord:dev",
        )
        rejected_loop = await service.execute(same_audience)
        assert rejected_loop.status == "failed"
        assert rejected_loop.error == "relay target audience must differ from its source audience"

    try:
        asyncio.run(scenario())
    finally:
        ledger.close()


def test_mcp_inbound_delivery_observation_and_self_authored_quarantine(project_root: Path) -> None:
    _write_communication_apps(project_root)
    configuration = load_configuration(project_root)
    ledger = MCPPublicationLedger(project_root / "inbound-test.sqlite3")

    async def call_tool(_tool: str, arguments: dict[str, object]) -> dict[str, object]:
        return {
            "status": "accepted",
            "delivery_id": arguments["delivery_id"],
            "external_message_id": "external-loop-message",
        }

    service = MCPPublicationService(configuration, ledger, call_tool)
    ingress = _Ingress()
    platform = MCPPlatform(configuration)
    platform._ledger = ledger
    platform._ingress = ingress

    async def scenario() -> None:
        request = _request(configuration.apps_configuration_hash)
        assert (await service.execute(request)).status == "accepted"
        await platform._handle_notification(
            "com.example.discord",
            "aurora/event",
            _notification(
                external_event_id="loop-event",
                external_message_id="external-loop-message",
                authored_by_self=True,
                origin_delivery_id="delivery-1",
            ),
        )
        ledger.record_started(
            "delivery-started",
            "digest",
            "com.example.discord",
            "com.example.discord.relay",
            "com.example.discord.publish",
        )
        await platform._handle_notification(
            "com.example.discord",
            "aurora/event",
            _notification(
                external_event_id="started-event",
                external_message_id="external-started-message",
                authored_by_self=False,
                origin_delivery_id="delivery-started",
            ),
        )
        await platform._handle_notification(
            "com.example.discord",
            "aurora/event",
            _notification(
                external_event_id="self-event",
                external_message_id="external-without-ledger",
                authored_by_self=True,
                origin_delivery_id=None,
            ),
        )
        malformed = _notification(
            external_event_id="malformed-event",
            external_message_id="external-malformed",
            authored_by_self=False,
            origin_delivery_id=None,
        )
        malformed["endpoint_id"] = "spoofed.endpoint"
        await platform._handle_notification("com.example.discord", "aurora/event", malformed)
        await platform._handle_notification(
            "com.example.discord",
            "aurora/event",
            _notification(
                external_event_id="user-event",
                external_message_id="external-user-message",
                authored_by_self=False,
                origin_delivery_id=None,
            ),
        )

        assert len(ingress.values) == 1
        amp = AmpEnvelope.parse(ingress.values[0])
        communication = amp.payload.data["communication"]
        assert communication["endpoint_id"] == "com.example.discord"
        assert "authored_by_self" not in communication
        assert "origin_delivery_id" not in communication
        assert amp.header.source["instance"] == "mcp:com.example.discord"
        assert amp.payload.session_id == communication["audience_ref"]
        quarantines = ledger._database.execute("SELECT reason FROM inbound_quarantine").fetchall()
        assert len(quarantines) == EXPECTED_QUARANTINES
        assert any("started" in str(row["reason"]) for row in quarantines)
        observed = ledger._database.execute(
            "SELECT delivery_observed_at FROM publications WHERE request_id = 'delivery-1'"
        ).fetchone()
        assert observed is not None and observed["delivery_observed_at"] is not None

    try:
        asyncio.run(scenario())
    finally:
        ledger.close()
