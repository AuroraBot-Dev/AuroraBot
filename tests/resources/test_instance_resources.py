"""真实认知实例经统一资源入口发现，并在重启后检查原始版本。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from aurora import load_config
from aurora.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora.configs.engine import CONFIG_SPEC as ENGINE_CONFIG
from aurora.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG
from aurorabot.contracts.operation import OperationKind, OperationRequest, OperationStatus
from aurorabot.contracts.pkgs.operations import OperationRegistry
from aurorabot.contracts.resource import ResourceKey, ResourceRef
from aurorabot.contracts.resource_requests import RESOURCE_FIND, RESOURCE_INSPECT
from aurorabot.engine.config import EngineConfig
from aurorabot.mcp.config import PlatformsConfig
from aurorabot.runtime import compose_runtime
from tests.support.model import TemplateModel as FakeModel

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from aurorabot.contracts.operation import OperationResult
    from aurorabot.contracts.process import TreeProcessDefinition


def _query(request_id: str, target: ResourceRef, arguments: Mapping[str, Any]) -> OperationRequest:
    """使用 Bot 与终端共用的正式操作请求。"""
    return OperationRequest(request_id, "aurora:bot/default", "test", target, OperationKind.QUERY, arguments)


async def _recorded_views(
    registry: OperationRegistry, original: TreeProcessDefinition
) -> tuple[OperationResult, OperationResult]:
    """通过公共入口读取实际运行的完成版本与开始版本。"""
    found = await registry.dispatch(_query("find-instance", RESOURCE_FIND, {"domain": "engine", "kind": "instance"}))
    assert found.status is OperationStatus.SUCCEEDED
    assert len(found.data["items"]) == 1
    item = found.data["items"][0]
    args = {"resource": item["resource"], "revision": item["revision"]}
    completed = await registry.dispatch(_query("inspect-completed", RESOURCE_INSPECT, args))
    assert completed.status is OperationStatus.SUCCEEDED
    assert completed.data == item
    metadata = completed.data["metadata"]
    assert metadata["state"] == "completed"
    assert metadata["instance"]["instance_id"] == "森林/树:一"
    assert metadata["instance"]["definition"] == {"key": str(original.key), "revision": original.ref.revision}
    args = {"resource": item["resource"], "revision": f"world_{metadata['start_cursor']}"}
    started = await registry.dispatch(_query("inspect-started", RESOURCE_INSPECT, args))
    assert started.status is OperationStatus.SUCCEEDED
    assert started.data["metadata"]["state"] == "started"
    assert started.data["metadata"]["commit_count"] == 1
    return completed, started


def test_instance_discovery_and_historical_inspection_use_real_runtime_and_public_queries(
    configured_project: Path,
) -> None:
    """实际过程配置改变后，发现与检查仍保留旧实例采用的过程版本。"""
    config = load_config(configured_project)
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    config = config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )
    config = config.with_value(ENGINE_CONFIG, EngineConfig(2, 3, 1))

    async def scenario() -> None:
        """关闭真实连接后重建门面，通过固定引用读取相同历史状态与执行正文。"""
        runtime, lifecycle = await compose_runtime(config, FakeModel(), output=lambda _: None)
        original = runtime.runner.process_definition
        stop = asyncio.Event()
        stop.set()
        try:
            await lifecycle.activate(stop)
            await runtime.run("检查实例资源", tree_id="森林/树:一")
            completed, started = await _recorded_views(runtime.assembly.get(OperationRegistry), original)
        finally:
            await lifecycle.close()
        model = FakeModel()
        revised = config.with_value(ENGINE_CONFIG, EngineConfig(2, 3, 2))
        resumed, handle = await compose_runtime(revised, model, output=lambda _: None)
        try:
            await handle.activate(stop)
            assert resumed.runner.process_definition.ref != original.ref
            registry = resumed.assembly.get(OperationRegistry)
            completed_args = {"resource": completed.data["resource"], "revision": completed.data["revision"]}
            inspected = await registry.dispatch(_query("restart-completed", RESOURCE_INSPECT, completed_args))
            assert inspected.status is OperationStatus.SUCCEEDED
            assert inspected.data == completed.data
            started_args = {"resource": started.data["resource"], "revision": started.data["revision"]}
            earlier = await registry.dispatch(_query("restart-started", RESOURCE_INSPECT, started_args))
            assert earlier.data == started.data
            terminal = await resumed.terminal.dispatch_terminal("/resources --domain engine --kind instance")
            assert not terminal.is_error
            assert json.loads(terminal.text or "{}")["items"][0]["revision"] == completed.data["revision"]
            process = inspected.data["metadata"]["instance"]["definition"]
            read = await registry.dispatch(
                _query(
                    "read-instance-definition",
                    ResourceRef(ResourceKey.parse("aurora:artifacts/query/read"), "1"),
                    {**process, "encoding": "utf-8", "limit": 16384},
                )
            )
            assert read.status is OperationStatus.SUCCEEDED
            assert read.data["text"].encode() == original.content
            missing_revision = await registry.dispatch(
                _query("no-instance-version", RESOURCE_INSPECT, {"resource": completed.data["resource"]})
            )
            assert missing_revision.status is OperationStatus.FAILED
            assert not model.requests
        finally:
            await handle.close()

    asyncio.run(scenario())
