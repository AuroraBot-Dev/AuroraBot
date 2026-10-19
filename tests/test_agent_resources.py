"""Agent 原型身份、规范正文与运行时采用的目录保持一致。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from test_assembly import FakeModel
from test_kernel import _Settings

from aurora import load_config
from aurora.configs.agents import AGENTS_CONFIG
from aurora.configs.cadence import CADENCE_CONFIG
from aurora.configs.platforms import PLATFORMS_CONFIG
from src.agents import AgentCatalog as ConcreteCatalog
from src.agents.config import AgentsConfig
from src.agents.module import MODULE as AGENTS_MODULE
from src.artifacts.module import MODULE as ARTIFACTS_MODULE
from src.artifacts.store import FileArtifactStore
from src.contracts import TOOL_CONTRIBUTIONS, AgentDefinition
from src.contracts.agent_resource import AGENT_MEDIA_TYPE
from src.contracts.operation import OPERATION_CONTRIBUTIONS, OperationKind, OperationRequest, OperationStatus
from src.contracts.pkgs.agents import AgentCatalog
from src.contracts.pkgs.artifacts import ArtifactStore
from src.contracts.pkgs.operations import OperationRegistry
from src.contracts.pkgs.resources import ResourceCatalog
from src.contracts.resource import ResourceKey, ResourceRef
from src.contracts.resource_query import ResourceQuery
from src.kernel import compose_managed, module
from src.mcp.config import PlatformsConfig
from src.resource_content.module import MODULE as CONTENT_MODULE
from src.resources.module import MODULE as RESOURCES_MODULE
from src.runtime import compose_runtime

if TYPE_CHECKING:
    from pathlib import Path

    from src.kernel import ModuleContext


def _definition() -> AgentDefinition:
    """使用完整原生资源身份创建一个原型。"""
    return AgentDefinition(
        "lab:agent/definition/root", "研究原型", "lab:prompt/agent/research", "model", frozenset(), frozenset()
    )


@pytest.mark.parametrize("field", ["description", "prompt_id", "model", "tools", "children"])
def test_agent_version_covers_each_declaration(field: str) -> None:
    """正文摘要覆盖全部原型字段，能力集合变化不会沿用旧版本。"""
    original = _definition()
    changes = {
        "description": "另一个研究原型",
        "prompt_id": "lab:prompt/agent/review",
        "model": "other-model",
        "tools": frozenset({"lab:tool/read"}),
        "children": frozenset({"lab:agent/definition/worker"}),
    }
    changed = replace(original, **{field: changes[field]})
    assert original.ref.key == ResourceKey.parse(original.definition_id)
    assert original.ref.revision == hashlib.sha256(original.content).hexdigest()
    assert changed.ref != original.ref
    assert changed.content != original.content


def test_agent_canonical_content_sorts_sets_and_rejects_incomplete_resource_identity() -> None:
    """同一声明不因集合输入顺序改变版本，原型身份必须可由统一资源解析器直接读取。"""
    original = replace(_definition(), tools=frozenset({"lab:tool/z", "lab:tool/a"}))
    equivalent = replace(original, tools=frozenset(("lab:tool/a", "lab:tool/z")))
    assert original.content == equivalent.content
    assert original.ref == equivalent.ref
    assert json.loads(original.content)["tools"] == ["lab:tool/a", "lab:tool/z"]
    with pytest.raises(ValueError, match="Agent definition ID"):
        replace(original, definition_id="lab:agent/root")


def test_custom_agent_catalog_is_published_without_reading_builtin_configuration(tmp_path: Path) -> None:
    """替换目录之后，默认模组只保存被选中原型，测试配置无需任何 Agent 声明。"""
    expected = _definition()
    store = FileArtifactStore(tmp_path)

    @module(
        name="custom_agents",
        provides=AgentCatalog,
        priority=10,
        declares=(TOOL_CONTRIBUTIONS, OPERATION_CONTRIBUTIONS),
    )
    def custom(context: ModuleContext) -> AgentCatalog:
        """以不同命名空间提供实际选中的目录。"""
        return ConcreteCatalog((expected,))

    async def scenario() -> None:
        """通过真实动态资源来源发现并验证归档正文。"""
        lifecycle = await compose_managed(
            _Settings(),
            (AGENTS_MODULE, ARTIFACTS_MODULE, RESOURCES_MODULE, CONTENT_MODULE, custom),
            instances=((ArtifactStore, store),),
        )
        try:
            await lifecycle.activate(asyncio.Event())
            catalog = lifecycle.assembly.get(ResourceCatalog)
            page = await catalog.browse(ResourceQuery(domain="agent", kind="definition"))
            assert [item.ref for item in page.items] == [expected.ref]
            assert (await catalog.inspect(expected.ref)).metadata["content_verified"] is True
            assert (await store.read(expected.ref)).content == expected.content
        finally:
            await lifecycle.close()

    asyncio.run(scenario())


def test_actual_agent_definitions_remain_readable_after_config_change_and_restart(configured_project: Path) -> None:
    """真实配置展开后的原型可经公共入口读取，重启采用新版本同时保留旧正文。"""
    config = load_config(configured_project)
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    config = config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )
    identity = "aurora:agent/definition/root"

    async def scenario() -> None:
        """重建实际存储与目录，确认原始标签已展开为明确的工具身份。"""
        runtime, lifecycle = await compose_runtime(config, FakeModel(), output=lambda _: None)
        original = runtime.assembly.get(AgentCatalog).get(identity)
        try:
            await lifecycle.activate(asyncio.Event())
        finally:
            await lifecycle.close()
        agents = config.get(AGENTS_CONFIG)
        revised = config.with_value(
            AGENTS_CONFIG,
            AgentsConfig(
                tuple(
                    replace(item, description="新的主体说明") if item.id == identity else item for item in agents.agents
                )
            ),
        )
        resumed, handle = await compose_runtime(revised, FakeModel(), output=lambda _: None)
        try:
            await handle.activate(asyncio.Event())
            current = resumed.assembly.get(AgentCatalog).get(identity)
            assert current.ref != original.ref
            registry = resumed.assembly.get(OperationRegistry)
            for definition in (original, current):
                request = OperationRequest(
                    f"read-agent-{definition.ref.revision}",
                    "aurora:bot/default",
                    "test",
                    ResourceRef(ResourceKey.parse("aurora:artifacts/query/read"), "1"),
                    OperationKind.QUERY,
                    {"key": identity, "revision": definition.ref.revision, "encoding": "utf-8", "limit": 16384},
                )
                result = await registry.dispatch(request)
                assert result.status is OperationStatus.SUCCEEDED
                assert result.data["text"].encode("utf-8") == definition.content
                assert result.data["media_type"] == AGENT_MEDIA_TYPE
                body = json.loads(definition.content)
                assert frozenset(body["tools"]) == definition.tools
                assert all(not name.startswith("#") for name in body["tools"])
        finally:
            await handle.close()

    asyncio.run(scenario())
