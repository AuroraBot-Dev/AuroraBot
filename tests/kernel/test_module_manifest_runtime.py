"""实际插件声明通过公共查询与正文归档在重启后保留原版本。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from aurora_bot.contracts.module_manifest import MODULE_MANIFEST_MEDIA_TYPE
from aurora_bot.contracts.operation import OperationKind, OperationRequest, OperationStatus
from aurora_bot.contracts.pkgs.operations import OperationRegistry
from aurora_bot.contracts.resource import ResourceKey, ResourceRef
from aurora_bot.contracts.resource_requests import RESOURCE_FIND, RESOURCE_INSPECT
from aurora_bot.mcp.config import PlatformsConfig
from aurora_bot.runtime import compose_runtime
from aurora_cli import load_config
from aurora_cli.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora_cli.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG
from tests.support.model import TemplateModel as FakeModel

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from aurora_bot.contracts.resource import ResourceDescriptor
    from aurora_bot.runtime.core import AuroraRuntime

_PLUGIN = '''"""用于核对环境声明的独立插件。"""

from aurora_bot.kernel import ModuleManifest, module


@module(name="environment", provides=str, manifest=ModuleManifest({version!r}, namespace="lab"))
def build(context):
    """构造实际服务，发布声明不代替真实装配。"""
    return "环境可用"


MODULE = build
'''
_READ = ResourceRef(ResourceKey.parse("aurora:artifacts/query/read"), "1")


def _request(request_id: str, target: ResourceRef, arguments: Mapping[str, Any]) -> OperationRequest:
    """使用普通调用者共享的请求与版本入口。"""
    return OperationRequest(request_id, "aurora:bot/default", "test", target, OperationKind.QUERY, arguments)


async def _published(runtime: AuroraRuntime) -> tuple[ResourceDescriptor, bytes]:
    """公开查询、实际声明和归档正文三者使用同一版本。"""
    spec = next(spec for spec in runtime.assembly.modules if spec.module_id == "lab:kernel/module/environment")
    assert runtime.assembly.get(str) == "环境可用"
    registry = runtime.assembly.get(OperationRegistry)
    found = await registry.dispatch(
        _request("find-module", RESOURCE_FIND, {"namespace": "lab", "domain": "kernel", "kind": "module"})
    )
    assert found.status is OperationStatus.SUCCEEDED
    assert len(found.data["items"]) == 1
    item = found.data["items"][0]
    assert item["resource"] == spec.module_id
    assert item["revision"] == spec.resource.ref.revision
    inspected = await registry.dispatch(
        _request("inspect-module", RESOURCE_INSPECT, {"resource": item["resource"], "revision": item["revision"]})
    )
    assert inspected.data == item
    read = await registry.dispatch(
        _request("read-module", _READ, {"key": item["resource"], "revision": item["revision"], "encoding": "utf-8"})
    )
    assert read.status is OperationStatus.SUCCEEDED
    assert read.data["text"].encode() == spec.content
    assert read.data["media_type"] == MODULE_MANIFEST_MEDIA_TYPE
    return spec.resource, spec.content


def test_actual_plugin_manifest_is_discoverable_and_old_content_survives_restart(configured_project: Path) -> None:
    """插件发布版本改变后，旧声明仍能通过正式正文操作核对。"""
    directory = configured_project / "extensions" / "plugins"
    directory.mkdir(parents=True)
    plugin = directory / "environment.py"
    plugin.write_text(_PLUGIN.format(version="1.0"), encoding="utf-8")
    config = load_config(configured_project)
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    config = config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )

    async def scenario() -> None:
        """正式生命周期归档当前声明，重启使用真实新插件并读取旧正文。"""
        runtime, handle = await compose_runtime(config, FakeModel(), output=lambda _: None)
        stop = asyncio.Event()
        stop.set()
        try:
            await handle.activate(stop)
            original, content = await _published(runtime)
        finally:
            await handle.close()
        plugin.write_text(_PLUGIN.format(version="2.0.0"), encoding="utf-8")
        resumed, lifecycle = await compose_runtime(config, FakeModel(), output=lambda _: None)
        try:
            await lifecycle.activate(stop)
            spec = next(spec for spec in resumed.assembly.modules if spec.module_id == str(original.ref.key))
            assert spec.manifest.version == "2.0.0"
            assert spec.resource.ref != original.ref
            registry = resumed.assembly.get(OperationRegistry)
            read = await registry.dispatch(
                _request(
                    "read-prior-module",
                    _READ,
                    {"key": str(original.ref.key), "revision": original.ref.revision, "encoding": "utf-8"},
                )
            )
            assert read.status is OperationStatus.SUCCEEDED
            assert read.data["text"].encode() == content
            assert json.loads(read.data["text"])["version"] == "1.0"
            terminal = await resumed.terminal.dispatch_terminal(
                "/resources --namespace lab --domain kernel --kind module"
            )
            assert not terminal.is_error
            versions = {item["revision"] for item in json.loads(terminal.text or "{}")["items"]}
            assert versions == {original.ref.revision, spec.resource.ref.revision}
        finally:
            await lifecycle.close()

    asyncio.run(scenario())
