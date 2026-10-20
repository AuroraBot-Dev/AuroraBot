"""从真实节律日志读取可标注观察的领域查询测试。"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from aurora import load_config
from aurora.configs.rhythm import CONFIG_SPEC as RHYTHM_CONFIG
from aurorabot.contracts import EnvironmentEvent
from aurorabot.contracts.pkgs.cadence import Cadence
from aurorabot.rhythm.config import RhythmConfig
from aurorabot.runtime import assemble_runtime
from tests.model_support import TemplateModel as FakeModel

if TYPE_CHECKING:
    from pathlib import Path


def test_observations_can_be_read_without_inventing_utility_labels(configured_project: Path) -> None:
    """训练输入来自决策当时的事实，正确效用需要独立标注或回放。"""

    async def scenario() -> None:
        config = load_config(configured_project).with_value(RHYTHM_CONFIG, RhythmConfig(evoke_every=5))
        model = FakeModel()
        runtime = assemble_runtime(config, model, output=lambda _: None)
        try:
            await runtime.submit_event(
                EnvironmentEvent(
                    "first", "test", "test:world", "message", datetime(2026, 10, 18, tzinfo=UTC), "外部变化"
                )
            )
            await runtime.assembly.get(Cadence).evaluate_once()
            response = await runtime.terminal.dispatch_terminal('/call aurora:rhythm/query/observations {"limit":1}')
            assert not response.is_error
            data = json.loads(response.text or "{}")["data"]
            observation = data["observations"][0]
            assert observation["observation"]["pending_events"] == 1
            assert observation["decision"]["action"] == "wait"
            assert "think_value" not in observation and "wait_value" not in observation
            after = data["cursor"]
            continued = await runtime.terminal.dispatch_terminal(
                f'/call aurora:rhythm/query/observations {{"after":{after},"limit":1}}'
            )
            assert json.loads(continued.text or "{}")["data"]["observations"] == []
            assert model.requests == []
        finally:
            await runtime.world.close()

    asyncio.run(scenario())
