from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.contracts.agent import (
    AgentContext,
    AgentDecision,
    CapabilityDescriptor,
    PublicationRequest,
    TaskStatus,
)
from src.contracts.configuration import load_configuration
from src.localhost.ports import PublicationExecutorBinding
from src.localhost.runtime import AuroraRuntime
from src.platform.mcp import MCPPlatform
from src.platform.mcp.communication import publication_descriptor_schema
from src.platform.mcp.publication import MCPPublicationService
from src.platform.mcp.publication_ledger import MCPPublicationLedger

if TYPE_CHECKING:
    from pathlib import Path


QQ_ENDPOINT = "com.example.qq"
QQ_REPLY = "com.example.qq.reply"
DISCORD_ENDPOINT = "com.example.discord"
DISCORD_RELAY = "com.example.discord.relay"


class _RelayThenReplyHandler:
    def handle(self, context: AgentContext) -> AgentDecision:
        if context.message.type == "task.started":
            return AgentDecision(
                publication_request=PublicationRequest(
                    "relay",
                    "relay to Discord",
                    "continue",
                    destination="discord.dev",
                )
            )
        assert context.message.type == "publication.succeeded"
        return AgentDecision(
            publication_request=PublicationRequest(
                "reply",
                "reply to QQ",
                "complete_on_success",
                route_ref="qq-private-route",
            )
        )


def _configure_communication_apps(project_root: Path) -> None:
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
address_ref = "discord-private-address"
allowed_source_audiences = ["com.example.qq:*"]
target_audience_ref = "com.example.discord:dev"
""",
        encoding="utf-8",
    )
    agents = project_root / "config" / "agents.toml"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace(
            'capabilities = ["org.aurora.console.send_message"]',
            'capabilities = ["com.example.qq.reply", "com.example.discord.relay"]',
        ),
        encoding="utf-8",
    )


def _descriptor(capability: str, endpoint: str, operation: str) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        id=capability,
        description=operation,
        parameters_schema=publication_descriptor_schema(operation),
        kind="publication",
        endpoint=endpoint,
        operation=operation,  # type: ignore[arg-type]
        root_only=True,
    )


def test_canonical_qq_message_relays_then_replies_and_completes(project_root: Path) -> None:
    _configure_communication_apps(project_root)

    async def scenario() -> None:
        configuration = load_configuration(project_root)
        runtime = AuroraRuntime.create(
            project_root,
            configuration=configuration,
            executor_bindings=None,
            publication_bindings=None,
        )
        runtime.kernel._handlers["builtin.gate"] = _RelayThenReplyHandler()
        platform = MCPPlatform(configuration)
        ledger = MCPPublicationLedger(project_root / "integration-publications.sqlite3")
        calls: list[tuple[str, dict[str, object]]] = []

        async def call_tool(tool: str, arguments: dict[str, object]) -> dict[str, object]:
            calls.append((tool, arguments))
            return {
                "status": "accepted",
                "delivery_id": arguments["delivery_id"],
                "external_message_id": f"external-{len(calls)}",
            }

        platform._ledger = ledger
        platform._publications = MCPPublicationService(configuration, ledger, call_tool)
        platform._ingress = runtime
        platform._started = True
        descriptors = (
            _descriptor(QQ_REPLY, QQ_ENDPOINT, "reply"),
            _descriptor(DISCORD_RELAY, DISCORD_ENDPOINT, "relay"),
        )
        runtime.bind_platform_executors(
            (),
            tuple(
                PublicationExecutorBinding(descriptor, platform, platform, "platform.mcp", descriptor.endpoint or "")
                for descriptor in descriptors
            ),
        )
        try:
            await platform._handle_notification(
                QQ_ENDPOINT,
                "aurora/event",
                {
                    "type": "message.received",
                    "external_event_id": "qq-event-1",
                    "external_message_id": "qq-message-1",
                    "conversation_ref": "qq-private-conversation",
                    "actor_ref": "qq-private-actor",
                    "reply_route_ref": "qq-private-route",
                    "authored_by_self": False,
                    "origin_delivery_id": None,
                    "summary": "QQ message",
                    "data": {"text": "relay and reply"},
                },
            )

            started = await runtime.pump()
            assert started["publication_receipts_emitted"] == 1
            resumed = await runtime.pump()
            assert resumed["publication_receipts_emitted"] == 1
            await runtime.pump()

            task = runtime.kernel.get_task(started["ingested_task_ids"][0])
            assert task is not None and task.status == TaskStatus.COMPLETED
            assert task.termination_reason == "publication_succeeded"
            assert [arguments["operation"] for _tool, arguments in calls] == ["relay", "reply"]
            assert calls[0][1]["address_ref"] == "discord-private-address"
            assert calls[1][1]["route_ref"] == "qq-private-route"
        finally:
            await runtime.shutdown()
            ledger.close()

    asyncio.run(scenario())
