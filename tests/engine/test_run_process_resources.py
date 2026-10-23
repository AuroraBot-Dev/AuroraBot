from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from aurora_bot.contracts.operation import OperationKind, OperationRequest, OperationStatus
from aurora_bot.contracts.process import CognitionProcess
from aurora_bot.contracts.resource import ResourceKey, ResourceRef
from aurora_bot.engine import CognitionEngine
from aurora_bot.engine.config import EngineConfig
from aurora_bot.mcp.config import PlatformsConfig
from aurora_bot.runtime import compose_runtime
from aurora_cli import load_config
from aurora_cli.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora_cli.configs.engine import CONFIG_SPEC as ENGINE_CONFIG
from aurora_cli.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG
from aurora_kernel import Context
from tests.support.model import TemplateModel

if TYPE_CHECKING:
    from pathlib import Path


def test_process_version_covers_every_execution_setting() -> None:
    original = CognitionProcess()
    assert original.ref.revision == hashlib.sha256(original.content).hexdigest()
    for changed in (
        replace(original, max_model_calls=1),
        replace(original, max_tool_calls=1),
        replace(original, max_context_chars=1000),
        replace(original, strategy="direct"),
        replace(original, key=ResourceKey.parse("lab:engine/process/bounded")),
    ):
        assert changed.ref != original.ref


@pytest.mark.parametrize("limit", [0, -1, True])
def test_process_limits_are_valid_integers(limit: int) -> None:
    with pytest.raises(ValueError, match=r"上限|上界"):
        CognitionProcess(max_model_calls=limit)


def test_runner_cannot_label_its_loop_as_an_unimplemented_strategy() -> None:
    with pytest.raises(ValueError, match="不支持认知策略"):
        CognitionEngine(Context(), None, bot_id="aurora:bot/default", process=CognitionProcess(strategy="direct"))


def test_instance_keeps_original_process_after_config_change_and_restart(configured_project: Path) -> None:
    config = load_config(configured_project)
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    config = config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )
    config = config.with_value(ENGINE_CONFIG, EngineConfig(2, 3, 100000))

    async def scenario() -> None:
        runtime, lifecycle = await compose_runtime(config, TemplateModel(), output=lambda _: None)
        original = runtime.runner.process_definition
        stop = asyncio.Event()
        stop.set()
        try:
            await lifecycle.activate(stop)
            result = await runtime.run("读取运行依据", run_id="process:run")
            assert result.status == "completed"
        finally:
            await lifecycle.close()
        resumed, handle = await compose_runtime(
            config.with_value(ENGINE_CONFIG, EngineConfig(3, 3, 100000)), TemplateModel(), output=lambda _: None
        )
        try:
            await handle.activate(stop)
            assert resumed.runner.process_definition.ref != original.ref
            started = await resumed.world.commit("process:run:run:started")
            assert started is not None
            assert started.data["process_ref"] == {"key": str(original.key), "revision": original.ref.revision}
            request = OperationRequest(
                "read-original-process",
                "aurora:bot/default",
                "test",
                ResourceRef(ResourceKey.parse("aurora:artifacts/query/read"), "1"),
                OperationKind.QUERY,
                {**started.data["instance"]["definition"], "encoding": "utf-8", "limit": 16384},
            )
            result = await resumed.assembly.get("operations").dispatch(request)
            assert result.status is OperationStatus.SUCCEEDED
            assert result.data["text"].encode("utf-8") == original.content
        finally:
            await handle.close()

    asyncio.run(scenario())
