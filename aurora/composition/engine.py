"""构造并导出 ``src.engine`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey, ModuleSpec
from aurora.composition.agents import AGENTS
from aurora.composition.ai import MODEL
from aurora.composition.memory import MEMORY
from aurora.composition.prompt import PROMPT_ASSEMBLER
from aurora.composition.tools import TOOLS
from aurora.composition.world import WORLD_JOURNAL
from aurora.configuration.cadence import CADENCE_CONFIG
from aurora.configuration.endpoints import ENDPOINTS_CONFIG
from aurora.configuration.engine import ENGINE_CONFIG
from aurora.configuration.runtime import RUNTIME_CONFIG
from src.cadence import DEFAULT_REACTIVE_RULES
from src.engine import AgentTreeRunner
from src.tools import DELEGATE_TOOL

if TYPE_CHECKING:
    from collections.abc import Mapping

    from aurora.composer import CompositionContext
    from src.contracts import AgentDefinition


ENGINE_RUNNER = InstanceKey[AgentTreeRunner]("engine.runner")


def _validate_cross_references(
    definitions: tuple[AgentDefinition, ...],
    agent_ids: frozenset[str],
    prompts: Mapping[str, str],
    endpoint_ids: frozenset[str],
    tool_names: frozenset[str],
    runtime_agent: str,
    cadence_agent: str,
    cadence_reactive_agents: frozenset[str],
) -> None:
    """校验所有 agent 引用的外部资源是否存在。"""
    if runtime_agent not in agent_ids:
        raise ValueError(f"root 引用了未知 Agent definition：{runtime_agent}")
    unknown_cadence = ({cadence_agent} | cadence_reactive_agents) - agent_ids
    if unknown_cadence:
        raise ValueError(f"cadence 引用了未知 Agent definition：{', '.join(sorted(unknown_cadence))}")
    for definition in definitions:
        if definition.prompt_id not in prompts:
            raise ValueError(f"{definition.definition_id} 引用了未知 Agent prompt：{definition.prompt_id}")
        if definition.model not in endpoint_ids:
            raise ValueError(f"{definition.definition_id} 引用了未知 model endpoint：{definition.model}")
        missing = definition.tools - tool_names
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"{definition.definition_id} 引用了不可用工具：{names}")
        if bool(definition.children) != (DELEGATE_TOOL in definition.tools):
            raise ValueError(f"{definition.definition_id} 的 children 与 {DELEGATE_TOOL} 可见性不一致")


def _register(context: CompositionContext) -> None:
    configuration = context.config.get(ENGINE_CONFIG)
    runtime = context.config.get(RUNTIME_CONFIG)
    assembler = context.require(PROMPT_ASSEMBLER)
    model = context.require(MODEL)
    agents = context.require(AGENTS)
    tools = context.require(TOOLS)
    world = context.require(WORLD_JOURNAL)
    memory = context.require(MEMORY)
    prompts = assembler.catalog.agent_prompts
    endpoint_ids = frozenset(endpoint.name for endpoint in context.config.get(ENDPOINTS_CONFIG))
    cadence_agent = context.config.get(CADENCE_CONFIG).agent
    _validate_cross_references(
        agents.definitions,
        agents.ids,
        prompts,
        endpoint_ids,
        tools.names,
        runtime.agent,
        cadence_agent,
        frozenset(rule.agent for rule in DEFAULT_REACTIVE_RULES),
    )
    context.provide(
        ENGINE_RUNNER,
        AgentTreeRunner(
            model,
            assembler,
            agents,
            tools,
            world=world,
            memory=memory,
            max_depth=configuration.max_depth,
            max_nodes=configuration.max_nodes,
            max_steps=configuration.max_steps,
        ),
    )


MODULE_SPEC = ModuleSpec(
    key=ENGINE_RUNNER,
    requires=(PROMPT_ASSEMBLER, MODEL, AGENTS, TOOLS, WORLD_JOURNAL, MEMORY),
    register=_register,
)
