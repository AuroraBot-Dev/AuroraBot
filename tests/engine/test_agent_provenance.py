from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aurora_bot.contracts import ChatMessage, CognitionRequest
from aurora_bot.runtime import assemble_runtime
from aurora_cli import load_config
from tests.support.model import ScriptedModel

if TYPE_CHECKING:
    from pathlib import Path


def test_independent_runs_record_their_selected_profile_versions(configured_project: Path) -> None:
    async def scenario() -> None:
        model = ScriptedModel([ChatMessage.assistant("完成工作"), ChatMessage.assistant("完成审阅")])
        runtime = assemble_runtime(load_config(configured_project), model)
        profiles = ("aurora:agent/definition/worker", "aurora:agent/definition/reviewer")
        try:
            for index, profile in enumerate(profiles):
                result = await runtime.launch(CognitionRequest("独立任务", agent=profile, run_id=f"run-{index}"))
                assert result.status == "completed"
                definition = runtime.assembly.get("agents").get(profile)
                assert model.requests[index].resources[0] == definition.ref
                started = await runtime.world.commit(f"run-{index}:run:started")
                requested = await runtime.world.commit(f"run-{index}:model:0:requested")
                assert started is not None and requested is not None
                assert started.data["definition_ref"] == requested.data["definition_ref"]
                assert requested.data["definition_ref"]["revision"] == definition.ref.revision
                assert "parent_id" not in started.data
        finally:
            await runtime.world.close()

    asyncio.run(scenario())
