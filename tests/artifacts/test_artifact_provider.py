"""已发布的数据集和模型版本作为统一目录的动态来源。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from aurora_bot.contracts.artifact import ArtifactIntegrityError
from aurora_bot.contracts.pkgs.artifacts import ArtifactStore
from aurora_bot.contracts.pkgs.resources import ResourceCatalog
from aurora_bot.contracts.resource import ResourceKey
from aurora_bot.contracts.resource_query import ResourceQuery
from aurora_bot.runtime import assemble_runtime
from aurora_cli import load_config
from tests.support.model import TemplateModel as FakeModel

if TYPE_CHECKING:
    from pathlib import Path


def test_published_content_is_discoverable_without_entering_the_static_registry(configured_project: Path) -> None:
    """真实装配无需把每次发布写进冻结目录，检查内容会额外核对字节完整性。"""
    runtime = assemble_runtime(load_config(configured_project), FakeModel(), output=lambda _: None)

    async def scenario() -> None:
        """发现未加载的内容，并验证损坏文件不能通过检查入口。"""
        try:
            await runtime.world.initialize()
            store = runtime.assembly.get(ArtifactStore)
            catalog = runtime.assembly.get(ResourceCatalog)
            key = ResourceKey.parse("lab:memory/model/not-loaded")
            info = await store.put(key, b"weight bytes")
            assert catalog.find(namespace="lab") == ()
            page = await catalog.browse(ResourceQuery(namespace="lab"))
            assert tuple(item.ref for item in page.items) == (info.ref,)
            assert page.items[0].metadata["content_verified"] is False
            inspected = await catalog.inspect(info.ref)
            assert inspected.metadata["content_verified"] is True
            assert inspected.metadata["content"]["size"] == info.size
            path = next((configured_project / "data/artifacts/objects").rglob(info.ref.revision or ""))
            path.write_bytes(b"broken bytes")
            assert (await catalog.browse(ResourceQuery(namespace="lab"))).items
            with pytest.raises(ArtifactIntegrityError):
                await catalog.inspect(info.ref)
        finally:
            await runtime.world.close()

    asyncio.run(scenario())
