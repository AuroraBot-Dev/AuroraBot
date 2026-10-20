"""``aurorabot.engine`` 的自描述模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurorabot.contracts import DELEGATE_TOOL
from aurorabot.contracts.pkgs.agents import AgentCatalog
from aurorabot.contracts.pkgs.ai import Model
from aurorabot.contracts.pkgs.bot import BotStateStore
from aurorabot.contracts.pkgs.engine import AgentTreeRunner as AgentTreeRunnerPort
from aurorabot.contracts.pkgs.memory import MemoryReader
from aurorabot.contracts.pkgs.prompt import PromptAssembler
from aurorabot.contracts.pkgs.tools import ToolRegistry
from aurorabot.contracts.pkgs.world import WorldJournal
from aurorabot.contracts.process import TREE_PROCESS_MEDIA_TYPE, TreeProcessDefinition
from aurorabot.contracts.resource_content import RESOURCE_CONTENTS, ResourceContent
from aurorabot.contracts.scope import ScopeDeclaration, ScopeKind
from aurorabot.contracts.tree_lifecycle import TREE_SCOPE_PATTERN
from aurorabot.engine.config import EngineConfig
from aurorabot.engine.runtime import AgentTreeRunner
from aurorabot.kernel import ModuleContext, module

if TYPE_CHECKING:
    from collections.abc import Mapping


@module(
    name="engine",
    provides=AgentTreeRunnerPort,
    requires=(
        AgentTreeRunnerPort,
        PromptAssembler,
        Model,
        AgentCatalog,
        ToolRegistry,
        WorldJournal,
        MemoryReader,
        BotStateStore,
    ),
    contributes=RESOURCE_CONTENTS,
    scopes=ScopeDeclaration(
        TREE_SCOPE_PATTERN, ScopeKind.RUN, "一次 AgentTree 运行的因果台账；默认不自动召回，可按证据引用展开。"
    ),
)
def build(context: ModuleContext) -> AgentTreeRunnerPort:
    """过程资源来自实际被选中的运行器，不读取失选运行器的配置。"""
    runner = context.get_optional(AgentTreeRunnerPort)
    if runner is None:
        config = context.settings.resolve(EngineConfig)
        assembler = context.get(PromptAssembler)
        agents = context.get(AgentCatalog)
        tools = context.get(ToolRegistry)
        model = context.get(Model)
        _validate_cross_references(agents, assembler.catalog.agent_prompts, model, tools.names)
        runner = AgentTreeRunner(
            model,
            assembler,
            agents,
            tools,
            world=context.get(WorldJournal),
            memory=context.get(MemoryReader),
            bot_id=context.get(BotStateStore).bot_id,
            process=TreeProcessDefinition(config.max_depth, config.max_nodes, config.max_steps),
        )
    process = runner.process_definition
    context.contribute(RESOURCE_CONTENTS, ResourceContent(process.ref, process.content, TREE_PROCESS_MEDIA_TYPE))
    return runner


def _validate_cross_references(
    agents: AgentCatalog,
    prompts: Mapping[str, str],
    model: Model,
    tool_names: frozenset[str],
) -> None:
    for definition in agents.definitions:
        if definition.prompt_id not in prompts:
            raise ValueError(f"{definition.definition_id} 引用了未知 Agent prompt：{definition.prompt_id}")
        model.resolve_endpoint(definition.model)
        missing = definition.tools - tool_names
        if missing:
            raise ValueError(f"{definition.definition_id} 引用了不可用工具：{', '.join(sorted(missing))}")
        if bool(definition.children) != (DELEGATE_TOOL in definition.tools):
            raise ValueError(f"{definition.definition_id} 的 children 与 {DELEGATE_TOOL} 可见性不一致")


MODULE = build
