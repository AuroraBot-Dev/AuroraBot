"""真实发现、装配与生命周期使用同一 ctx，通用扩展无需声明 Bot 契约。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from aurora_bot.kernel import DirectorySource, ModuleContext, compose_managed, module
from aurora_bot.kernel.context import capability_name
from aurora_kernel import CLOSE, Context, Host, namespace
from aurora_kernel.discovery import DirectorySource as HostDirectorySource
from tests.kernel.support import Settings

if TYPE_CHECKING:
    from pathlib import Path

_PLUGIN = """from aurora_kernel import namespace

@namespace("extension", requires=("aurora:kernel/module/service",))
def extension(ctx):
    ctx["kernel.services"]["python:builtins.str"] = "changed"
    ctx["extension"]["events"] = []

@extension.callpoint("echo")
def echo(ctx, value):
    ctx["extension"]["events"] = [*ctx["extension"]["events"], value]
    return ctx["kernel.services"]["python:builtins.str"]

MODULE = extension
"""


def test_bot_and_discovered_namespace_share_context_and_lifecycle(tmp_path: Path) -> None:
    (tmp_path / "extension.py").write_text(_PLUGIN, encoding="utf-8")
    trace = []

    async def activate(context: ModuleContext) -> None:
        trace.append(context.ctx.call("extension:echo", "activated"))

    @module(name="service", provides=str, activate=activate)
    def service(_context: ModuleContext) -> str:
        return "initial"

    @namespace("observer", requires=("extension",))
    def observer(ctx: Context) -> None:
        assert ctx["kernel.services"][capability_name(str)] == "changed"

    @observer.on(CLOSE)
    def close(ctx: Context) -> None:
        trace.extend(ctx["extension"]["events"])

    async def scenario() -> None:
        lifecycle = await compose_managed(Settings(), (*DirectorySource(tmp_path).discover(), observer, service))
        assembly = lifecycle.assembly
        assert assembly.get(str) == "changed"
        assert assembly.modules == (service,)
        await lifecycle.activate(asyncio.Event())
        assert await assembly.ctx.acall("extension:echo", "called") == "changed"
        await lifecycle.close()
        with pytest.raises(RuntimeError, match="已关闭"):
            assembly.ctx.call("extension:echo", "late")

    asyncio.run(scenario())
    assert trace == ["changed", "activated", "called"]


def test_same_filename_in_different_directories_keeps_relative_imports_isolated(tmp_path: Path) -> None:
    sources = []
    for name in ("first", "second"):
        plugin = tmp_path / name / "feature"
        plugin.mkdir(parents=True)
        (plugin / "value.py").write_text(f"VALUE = {name!r}\n", encoding="utf-8")
        (plugin / "module.py").write_text(
            "from aurora_kernel import namespace\n"
            f'@namespace("{name}")\n'
            "def feature(ctx):\n"
            "    from .value import VALUE\n"
            f'    ctx["{name}"]["value"] = VALUE\n'
            "MODULE = feature\n",
            encoding="utf-8",
        )
        sources.append(HostDirectorySource(plugin.parent))
    # 在两个入口均完成导入后才构造，避免入口导入顺序掩盖缓存覆盖。
    host = Host(tuple(spec for source in sources for spec in source.discover())).build()
    assert host.ctx["first"]["value"] == "first"
    assert host.ctx["second"]["value"] == "second"
