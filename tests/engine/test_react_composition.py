from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import TYPE_CHECKING

from aurora_bot.contracts import CognitionRequest
from aurora_bot.engine.module import MODULE
from aurora_bot.kernel import BuiltinSource, DirectorySource, compose_managed
from aurora_bot.mcp.config import PlatformsConfig
from aurora_cli import load_config
from aurora_cli.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG
from tests.support.model import TemplateModel

if TYPE_CHECKING:
    from pathlib import Path

_PLUGIN = """from dataclasses import replace
from aurora_bot.contracts import ChatMessage
from aurora_kernel import namespace

@namespace("custom_react", requires=("aurora:kernel/module/ai",))
def plugin(ctx):
    ctx["custom_react"]["requests"] = 0

@plugin.hook("aurora:kernel/module/ai:complete", priority=10)
async def reason(ctx, request):
    with ctx.transaction() as staged:
        staged["custom_react"]["requests"] += 1
    return ChatMessage.assistant("自定义推理完成")

MODULE = plugin
"""


def test_discovered_hook_participates_in_the_composed_bot_engine(configured_project: Path) -> None:
    directory = configured_project / "extensions" / "plugins"
    directory.mkdir(parents=True)
    (directory / "custom.py").write_text(_PLUGIN, encoding="utf-8")
    settings = load_config(configured_project)
    settings = settings.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in settings.get(PLATFORMS_CONFIG).platforms)),
    )

    async def scenario() -> None:
        lifecycle = await compose_managed(
            settings,
            (*BuiltinSource().discover(), *DirectorySource(directory).discover()),
            instances=(("ai", TemplateModel()),),
        )
        assembly = lifecycle.assembly
        try:
            result = await assembly.ctx.acall(
                "aurora:kernel/module/engine:execute",
                CognitionRequest("检查扩展", agent="aurora:agent/definition/root", run_id="composed-hooks"),
            )
            assert result.output == "自定义推理完成"
            assert assembly.ctx["custom_react"]["requests"] == 1
            committed = await assembly.get("world").commit("composed-hooks:output:committed")
            assert committed is not None and committed.data["content"] == "自定义推理完成"
            manifest = json.loads(MODULE.content)
            assert {point["name"] for point in manifest["callpoints"]} == {point.name for point in MODULE.points}
            assert len(manifest["handlers"]) == len(MODULE.handlers)
        finally:
            await lifecycle.close()

    asyncio.run(scenario())
