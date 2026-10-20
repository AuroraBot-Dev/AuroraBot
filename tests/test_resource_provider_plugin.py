"""第三方资源来源无需修改宿主目录或查询入口。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from test_assembly import FakeModel

from aurora import load_config
from aurorabot.runtime import assemble_runtime

if TYPE_CHECKING:
    from pathlib import Path

_PLUGIN = '''"""独立资源提供者。"""

from aurorabot.contracts.pkgs.resources import RESOURCE_PROVIDERS
from aurorabot.contracts.resource import ResourceDescriptor, ResourceKey, ResourceRef
from aurorabot.contracts.resource_paging import resource_order, resource_position
from aurorabot.contracts.resource_query import ResourcePage
from aurorabot.kernel import module

_ENTRY = ResourceDescriptor(
    ResourceRef(ResourceKey.parse("lab:experiments/dataset/measurements"), "edition-1"),
    "实验测量集",
)


class Measurements:
    """由扩展自行维护内容位置与版本。"""

    key = ResourceKey.parse("lab:experiments/provider/measurements")

    async def find(self, query):
        """此示例来源只有一项，仍严格遵守筛选与续页边界。"""
        after = resource_position(query)
        visible = query.matches(_ENTRY.ref.key) and (after is None or resource_order(_ENTRY.ref) > after)
        return ResourcePage((_ENTRY,) if visible else ())

    async def resolve(self, ref):
        """不由此来源负责的版本返回空值。"""
        return _ENTRY if ref == _ENTRY.ref else None


@module(name="measurements", contributes=RESOURCE_PROVIDERS)
def build(context):
    """只声明资源来源，不接触宿主实现。"""
    context.contribute(RESOURCE_PROVIDERS, Measurements())


MODULE = build
'''


def test_plugin_provider_is_visible_through_unchanged_terminal_queries(configured_project: Path) -> None:
    """非内容摘要版本也能通过统一发现和检查入口访问。"""
    directory = configured_project / "extensions" / "plugins"
    directory.mkdir(parents=True)
    (directory / "measurements.py").write_text(_PLUGIN, encoding="utf-8")
    runtime = assemble_runtime(load_config(configured_project), FakeModel(), output=lambda _: None)

    async def scenario() -> None:
        """实际目录发现插件后，终端直接使用新增来源。"""
        try:
            found = await runtime.terminal.dispatch_terminal("/resources --namespace lab --domain experiments")
            assert not found.is_error
            data = json.loads(found.text or "{}")
            item = data["items"][0]
            assert data["next_cursor"] is None
            assert item["revision"] == "edition-1"
            inspected = await runtime.terminal.dispatch_terminal(f"/inspect {item['resource']}@{item['revision']}")
            assert not inspected.is_error
            assert json.loads(inspected.text or "{}")["description"] == "实验测量集"
        finally:
            await runtime.world.close()

    asyncio.run(scenario())
