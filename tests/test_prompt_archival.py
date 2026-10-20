"""提示词历史正文在正式生命周期中持久化，并能经公共入口恢复。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from aurora import load_config
from aurora.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG
from aurorabot.artifacts.module import MODULE as ARTIFACTS_MODULE
from aurorabot.artifacts.store import FileArtifactStore
from aurorabot.contracts.artifact import ArtifactInfo
from aurorabot.contracts.operation import OPERATION_CONTRIBUTIONS, OperationKind, OperationRequest, OperationStatus
from aurorabot.contracts.pkgs.artifacts import ArtifactStore
from aurorabot.contracts.pkgs.operations import OperationRegistry
from aurorabot.contracts.pkgs.prompt import PromptAssembler
from aurorabot.contracts.prompt import PROMPT_MEDIA_TYPE, PromptFragment
from aurorabot.contracts.resource import ResourceKey, ResourceRef
from aurorabot.kernel import compose_managed, module
from aurorabot.mcp.config import PlatformsConfig
from aurorabot.prompt import PromptAssembler as ConcreteAssembler
from aurorabot.prompt import PromptCatalog
from aurorabot.prompt.module import MODULE as PROMPT_MODULE
from aurorabot.resource_content.module import MODULE as CONTENT_MODULE
from aurorabot.resources.module import MODULE as RESOURCES_MODULE
from aurorabot.runtime import compose_runtime
from tests.kernel_support import Settings as _Settings
from tests.model_support import TemplateModel as FakeModel

if TYPE_CHECKING:
    from pathlib import Path

    from aurorabot.kernel import ModuleContext


def test_recorded_prompt_body_survives_source_replacement_and_runtime_restart(configured_project: Path) -> None:
    """重启后从世界事实取出旧版本，经正式读取操作取得当时实际使用的正文。"""
    config = load_config(configured_project)
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    config = config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )
    key = ResourceKey.parse("aurora:prompt/agent/root")

    async def scenario() -> None:
        """先运行并关闭全部模组，再用新目录与新存储实例读取旧正文。"""
        runtime, lifecycle = await compose_runtime(config, FakeModel(), output=lambda _: None)
        original = runtime.assembly.get(PromptAssembler).catalog.get(ResourceRef(key))
        try:
            await lifecycle.activate(asyncio.Event())
            tree = await runtime.run("记录本次提示词", tree_id="archived-prompt")
        finally:
            await lifecycle.close()
        source = configured_project / "config" / "prompts" / "builtin" / "root.md"
        source.write_text("这是重启后采用的新提示词。", encoding="utf-8")
        resumed, handle = await compose_runtime(config, FakeModel(), output=lambda _: None)
        try:
            await handle.activate(asyncio.Event())
            current = resumed.assembly.get(PromptAssembler).catalog.get(ResourceRef(key))
            assert current.ref != original.ref
            fact = await resumed.world.commit(f"archived-prompt:{tree.root_id}:model:0:requested")
            assert fact is not None
            recorded = next(item for item in fact.data["resources"] if item["key"] == str(key))
            assert recorded["revision"] == original.ref.revision
            request = OperationRequest(
                "read-historical-prompt",
                "aurora:bot/default",
                "test",
                ResourceRef(ResourceKey.parse("aurora:artifacts/query/read"), "1"),
                OperationKind.QUERY,
                {**recorded, "encoding": "utf-8", "limit": 16384},
            )
            result = await resumed.assembly.get(OperationRegistry).dispatch(request)
            assert result.status is OperationStatus.SUCCEEDED
            assert result.data["text"] == original.content
            assert result.data["media_type"] == PROMPT_MEDIA_TYPE
            assert result.data["has_more"] is False
            assert (await resumed.assembly.get(ArtifactStore).read(current.ref)).content == current.content.encode()
        finally:
            await handle.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("wrong_revision", [False, True])
def test_failed_prompt_publication_prevents_background_start(tmp_path: Path, *, wrong_revision: bool) -> None:
    """正文不能可靠绑定到引用时启动失败，后台认知没有机会使用无法追溯的输入。"""
    started: list[bool] = []

    class BrokenStore(FileArtifactStore):
        """模拟选中存储不可写或违反内容版本契约。"""

        async def put(
            self, key: ResourceKey, content: bytes, *, media_type: str = "application/octet-stream"
        ) -> ArtifactInfo:
            """返回错误摘要与实际写入错误必须同样阻止运行。"""
            if not wrong_revision:
                raise OSError("内容存储不可写")
            return ArtifactInfo(ResourceRef(key, "0" * 64), len(content), media_type)

    async def run(context: ModuleContext, stop: asyncio.Event) -> None:
        """若启动阶段失守，记录后台已开始执行。"""
        started.append(True)

    @module(
        name="selected",
        provides=(PromptAssembler, ArtifactStore),
        priority=10,
        declares=OPERATION_CONTRIBUTIONS,
        run=run,
    )
    def selected(context: ModuleContext) -> None:
        """同时替换文本与存储，默认模块仍负责发布选中实例的资源。"""
        fragments = (
            PromptFragment(ResourceKey.parse("lab:prompt/system/identity"), "身份"),
            PromptFragment(ResourceKey.parse("lab:prompt/agent/root"), "认知"),
        )
        context.provide(PromptAssembler, ConcreteAssembler(PromptCatalog(fragments)))
        context.provide(ArtifactStore, BrokenStore(tmp_path))

    async def scenario() -> None:
        """激活失败自动关闭后，再次关闭仍可安全完成。"""
        lifecycle = await compose_managed(
            _Settings(), (PROMPT_MODULE, ARTIFACTS_MODULE, RESOURCES_MODULE, CONTENT_MODULE, selected)
        )
        try:
            error = ValueError if wrong_revision else OSError
            message = "不一致的版本" if wrong_revision else "内容存储不可写"
            with pytest.raises(error, match=message):
                await lifecycle.activate(asyncio.Event())
            await asyncio.sleep(0)
            assert not started
        finally:
            await lifecycle.close()

    asyncio.run(scenario())
