from __future__ import annotations

import asyncio
from pathlib import Path

from src.ai.contracts import ModelRequest, ModelResult, ModelUsage
from src.kernel.events import new_amp
from src.localhost.runtime import AuroraRuntime


class _ClockDecisionGateway:
    async def complete(self, _request: ModelRequest) -> ModelResult:
        return ModelResult(
            model="test/clock",
            negotiated_capabilities=frozenset({"chat", "structured_output"}),
            response_mode="normalized",
            text="{}",
            data={
                "kind": "effect",
                "capability": "im.polaris.clock.get_current_time",
                "parameters": {},
                "summary": "Get current time",
            },
            usage=ModelUsage(),
            cost_usd=0.0,
        )


def test_clock_mcp_app_completes_a_model_requested_effect(project_root: Path) -> None:
    source_root = Path(__file__).parents[1]
    app_directory = (source_root / "src" / "apps" / "aurora-app-clock").as_posix()
    (project_root / "config" / "apps.toml").write_text(
        f"""adapter = []

[[app]]
package = "im.polaris.clock"
enabled = true
transport = "stdio"
working_dir = "{app_directory}"
command = ["uv", "run", "python", "mcp_server.py"]
timeout_seconds = 30
allowed_tools = [
  "im.polaris.clock.get_current_time",
  "im.polaris.clock.set_alarm",
  "im.polaris.clock.set_timer",
  "im.polaris.clock.list_alarms",
  "im.polaris.clock.cancel_alarm",
]
""",
        encoding="utf-8",
    )
    (project_root / "config" / "nodes.toml").write_text(
        """[[node]]
id = "builtin.model_decide"
enabled = true
implementation = "src.nodes.model_decide:ModelDecideNode"
inputs = ["message.received"]
outputs = ["effect.requested"]
capabilities = ["im.polaris.clock.get_current_time"]
model_roles = ["fast"]

[[edge]]
event_type = "message.received"
target = "builtin.model_decide"
""",
        encoding="utf-8",
    )

    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        runtime.kernel._model_gateway = _ClockDecisionGateway()
        try:
            await runtime.submit_amp(
                new_amp(
                    event_type="message.received",
                    session_id="test:clock",
                    summary="what time is it",
                    data={"text": "what time is it"},
                    source_app="tests",
                    source_instance="mcp",
                ).to_dict()
            )
            result = await runtime.run_cycle()

            assert "im.polaris.clock.get_current_time" in runtime.configuration.capability_definitions
            assert result["platform_receipts_emitted"] == 1

            records = runtime.kernel._records()
            effect = next(record for record in records if record.amp["payload"]["type"] == "effect.requested")
            assert effect.amp["payload"]["data"]["capability"] == "im.polaris.clock.get_current_time"

            next_cycle = await runtime.run_cycle()
            receipt = runtime.kernel.get_record(next_cycle["ingested_record_ids"][0])
            assert receipt is not None
            assert receipt.amp["payload"]["type"] == "effect.succeeded"
            assert receipt.parent_record_id == effect.record_id

            timer = await runtime.mcp_platform._call_tool(
                "im.polaris.clock.set_timer", {"seconds": 1, "label": "test notification"}
            )
            assert timer["ok"] is True
            await asyncio.sleep(1.1)
            notification_cycle = await runtime.run_cycle()
            notification = runtime.kernel.get_record(notification_cycle["ingested_record_ids"][0])
            assert notification is not None
            assert notification.amp["payload"]["type"] == "timer.triggered"
            assert notification.amp["header"]["source"]["app"] == "im.polaris.clock"
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
