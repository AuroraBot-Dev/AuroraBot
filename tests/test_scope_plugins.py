"""本地插件的域声明同时服务 Bot 发现与默认记忆过滤。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from test_assembly import FakeModel

from aurora import load_config
from aurorabot.contracts import ScopeCatalog, ScopeKind, ToolCall, ToolOutput, WorldFrontier
from aurorabot.contracts.memory import MemoryRequest
from aurorabot.contracts.pkgs.memory import MemoryReader
from aurorabot.contracts.pkgs.tools import ToolRegistry
from aurorabot.runtime import assemble_runtime
from aurorabot.tools import WORLD_SCOPES_TOOL

if TYPE_CHECKING:
    from pathlib import Path

_PLUGIN = '''"""异步实验插件自行描述过程台账。"""

from aurorabot.contracts.scope import ScopeCatalog, ScopeDeclaration, ScopeKind
from aurorabot.kernel import ModuleContext, module


@module(
    name="lab_jobs",
    provides=str,
    requires=ScopeCatalog,
    scopes=ScopeDeclaration("lab:world/jobs/*", ScopeKind.RUN, "实验过程的投递台账"),
)
def build(context: ModuleContext) -> str:
    """插件可直接使用包含自身声明的目录。"""
    assert context.get(ScopeCatalog).classify("lab:world/jobs/one") is ScopeKind.RUN
    return "ready"


MODULE = build
'''


def test_directory_plugin_registers_its_run_domain_without_project_configuration(configured_project: Path) -> None:
    """宽泛世界域不会吞掉插件台账，工具和记忆对分类保持一致。"""
    plugin_directory = configured_project / "extensions" / "plugins"
    plugin_directory.mkdir(parents=True)
    (plugin_directory / "lab_scope.py").write_text(_PLUGIN, encoding="utf-8")
    settings = load_config(configured_project)
    assert settings.resolve(ScopeCatalog).declarations == ()
    runtime = assemble_runtime(settings, FakeModel(), output=lambda _: None)

    async def scenario() -> None:
        """通过实际装配的世界、工具和记忆端口检查声明效果。"""
        try:
            await runtime.world.initialize()
            for identity, scope in (("ledger", "lab:world/jobs/one"), ("fact", "lab:world/observations")):
                await runtime.world.append_commit(
                    commit_id=identity,
                    kind="lab.observed",
                    source="lab",
                    summary="实验结果已确认",
                    scopes=frozenset({scope}),
                    based_on=WorldFrontier(),
                    data={},
                )
            catalog = runtime.assembly.get(ScopeCatalog)
            assert catalog.classify("lab:world/jobs/one") is ScopeKind.RUN
            result = await runtime.assembly.get(ToolRegistry).execute(ToolCall("scopes", WORLD_SCOPES_TOOL))
            assert isinstance(result, ToolOutput)
            definitions = json.loads(result.content)["scopes"]
            assert next(item for item in definitions if item["pattern"] == "lab:world/jobs/*")["kind"] == "run"
            memory = await runtime.assembly.get(MemoryReader).recall(MemoryRequest(query="实验结果"))
            assert memory.recall is not None
            assert "fact" in {item.memory_id for item in memory.recall.ranking}
            assert "ledger" not in {item.memory_id for item in memory.recall.ranking}
        finally:
            await runtime.world.close()

    asyncio.run(scenario())
