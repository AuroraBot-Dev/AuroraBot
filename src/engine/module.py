"""``src.engine`` 的自描述模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import DELEGATE_TOOL
from src.contracts.pkgs.agents import AgentCatalog
from src.contracts.pkgs.ai import Model
from src.contracts.pkgs.bot import BotStateStore
from src.contracts.pkgs.engine import AgentTreeRunner as AgentTreeRunnerPort
from src.contracts.pkgs.memory import MemoryReader
from src.contracts.pkgs.prompt import PromptAssembler
from src.contracts.pkgs.tools import ToolRegistry
from src.contracts.pkgs.world import WorldJournal
from src.engine import AgentTreeRunner
from src.engine.config import EngineConfig
from src.engine.scopes import SCOPE_PATTERN as TREE_SCOPE_PATTERN
from src.kernel import ModuleContext, module

if TYPE_CHECKING:
    from collections.abc import Mapping


def _validate_cross_references(
    agents: AgentCatalog,
    prompts: Mapping[str, str],
    model: Model,
    tool_names: frozenset[str],
) -> None:
    for definition in agents.definitions:
        if definition.prompt_id not in prompts:
            raise ValueError(f"{definition.definition_id} 引用了未知 Agent prompt：{definition.prompt_id}")
        model.validate_endpoint(definition.model)
        missing = definition.tools - tool_names
        if missing:
            raise ValueError(f"{definition.definition_id} 引用了不可用工具：{', '.join(sorted(missing))}")
        if bool(definition.children) != (DELEGATE_TOOL in definition.tools):
            raise ValueError(f"{definition.definition_id} 的 children 与 {DELEGATE_TOOL} 可见性不一致")


@module(
    name="engine",
    provides=AgentTreeRunnerPort,
    requires=(PromptAssembler, Model, AgentCatalog, ToolRegistry, WorldJournal, MemoryReader, BotStateStore),
    owns_scopes=TREE_SCOPE_PATTERN,
)
def build(context: ModuleContext) -> AgentTreeRunnerPort:
    config = context.settings.resolve(EngineConfig)
    assembler = context.get(PromptAssembler)
    agents = context.get(AgentCatalog)
    tools = context.get(ToolRegistry)
    model = context.get(Model)
    _validate_cross_references(agents, assembler.catalog.agent_prompts, model, tools.names)
    return AgentTreeRunner(
        model,
        assembler,
        agents,
        tools,
        world=context.get(WorldJournal),
        memory=context.get(MemoryReader),
        bot_id=context.get(BotStateStore).bot_id,
        max_depth=config.max_depth,
        max_nodes=config.max_nodes,
        max_steps=config.max_steps,
    )


MODULE = build
