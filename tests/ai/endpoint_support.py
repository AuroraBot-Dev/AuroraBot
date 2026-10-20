"""复用的离线场景构造与替身，不依赖测试用例模块。"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from aurora import load_config
from aurora.configs.agents import CONFIG_SPEC as AGENTS_CONFIG
from aurora.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG
from aurorabot.agents.config import AgentsConfig
from aurorabot.contracts.operation import OperationKind, OperationRequest, OperationStatus
from aurorabot.contracts.pkgs.operations import OperationRegistry
from aurorabot.contracts.resource import ResourceKey, ResourceRef
from aurorabot.mcp.config import PlatformsConfig

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from aurora import AuroraConfig
    from aurorabot.runtime.core import AuroraRuntime


def _config(project: Path, endpoint_name: str) -> AuroraConfig:
    """隔离外部连接和自动认知，让所有原型显式使用待验证端点。"""
    config = load_config(project)
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    config = config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )
    return config.with_value(
        AGENTS_CONFIG,
        AgentsConfig(
            tuple(
                replace(item, model=endpoint_name, tools=(), children=frozenset())
                for item in config.get(AGENTS_CONFIG).agents
            )
        ),
    )


async def _read_definition(runtime: AuroraRuntime, reference: Mapping[str, Any], request_id: str) -> str:
    """历史正文使用正式操作路由读取，不从存储路径或当前配置反推。"""
    request = OperationRequest(
        request_id,
        "aurora:bot/default",
        "test",
        ResourceRef(ResourceKey.parse("aurora:artifacts/query/read"), "1"),
        OperationKind.QUERY,
        {**reference, "encoding": "utf-8", "limit": 16384},
    )
    result = await runtime.assembly.get(OperationRegistry).dispatch(request)
    assert result.status is OperationStatus.SUCCEEDED
    return result.data["text"]
