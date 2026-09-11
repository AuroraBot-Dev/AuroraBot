"""``src.engine`` 的自描述模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import (
    DELEGATE_TOOL,
    AgentCatalog,
    EndpointsConfig,
    MemoryReader,
    Model,
    PromptAssembler,
    RuntimeConfig,
    ToolRegistry,
    WorldJournal,
)
from src.contracts import (
    AgentTreeRunner as AgentTreeRunnerPort,
)
from src.engine import AgentTreeRunner
from src.engine.config import EngineConfig
from src.kernel import ModuleContext, module

if TYPE_CHECKING:
    from collections.abc import Mapping


def _validate_cross_references(
    agents: AgentCatalog,
    prompts: Mapping[str, str],
    endpoint_ids: frozenset[str],
    tool_names: frozenset[str],
    runtime_agent: str,
) -> None:
    if runtime_agent not in agents.ids:
        raise ValueError(f"root 引用了未知 Agent definition：{runtime_agent}")
    for definition in agents.definitions:
        if definition.prompt_id not in prompts:
            raise ValueError(f"{definition.definition_id} 引用了未知 Agent prompt：{definition.prompt_id}")
        if definition.model not in endpoint_ids:
            raise ValueError(f"{definition.definition_id} 引用了未知 model endpoint：{definition.model}")
        missing = definition.tools - tool_names
        if missing:
            raise ValueError(f"{definition.definition_id} 引用了不可用工具：{', '.join(sorted(missing))}")
        if bool(definition.children) != (DELEGATE_TOOL in definition.tools):
            raise ValueError(f"{definition.definition_id} 的 children 与 {DELEGATE_TOOL} 可见性不一致")


@module(
    name="engine",
    provides=AgentTreeRunnerPort,
    requires=(PromptAssembler, Model, AgentCatalog, ToolRegistry, WorldJournal, MemoryReader),
)
def build(context: ModuleContext) -> AgentTreeRunnerPort:
    config = context.settings.resolve(EngineConfig)
    runtime = context.settings.resolve(RuntimeConfig)
    assembler = context.get(PromptAssembler)
    agents = context.get(AgentCatalog)
    tools = context.get(ToolRegistry)
    endpoint_ids = frozenset(item.name for item in context.settings.resolve(EndpointsConfig).endpoints)
    _validate_cross_references(agents, assembler.catalog.agent_prompts, endpoint_ids, tools.names, runtime.agent)
    return AgentTreeRunner(
        context.get(Model),
        assembler,
        agents,
        tools,
        world=context.get(WorldJournal),
        memory=context.get(MemoryReader),
        max_depth=config.max_depth,
        max_nodes=config.max_nodes,
        max_steps=config.max_steps,
    )


MODULE = build
