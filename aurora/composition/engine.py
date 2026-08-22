"""构造并导出 ``src.engine`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey
from aurora.composition.agents import AGENTS
from aurora.composition.ai import MODEL
from aurora.composition.memory import MEMORY
from aurora.composition.prompt import PROMPT_ASSEMBLER
from aurora.composition.tools import TOOLS
from aurora.composition.world import WORLD_JOURNAL
from aurora.configuration.engine import ENGINE_CONFIG
from aurora.configuration.models import MODELS_CONFIG
from aurora.configuration.prompts import PROMPTS_CONFIG
from aurora.configuration.runtime import RUNTIME_CONFIG
from src.engine import AgentTreeRunner
from src.tools import DELEGATE_TOOL

if TYPE_CHECKING:
    from aurora.composer import CompositionContext


ENGINE_RUNNER = InstanceKey[AgentTreeRunner]("engine.runner")


def register(context: CompositionContext) -> None:
    configuration = context.config.get(ENGINE_CONFIG)
    runtime = context.config.get(RUNTIME_CONFIG)
    assembler = context.require(PROMPT_ASSEMBLER)
    model = context.require(MODEL)
    agents = context.require(AGENTS)
    tools = context.require(TOOLS)
    world = context.require(WORLD_JOURNAL)
    memory = context.require(MEMORY)
    prompts = context.config.get(PROMPTS_CONFIG).agent_prompts
    models = context.config.get(MODELS_CONFIG).endpoints
    if runtime.agent not in agents.ids:
        raise ValueError(f"root 引用了未知 Agent definition：{runtime.agent}")
    for definition in agents.definitions:
        if definition.prompt_id not in prompts:
            raise ValueError(f"{definition.definition_id} 引用了未知 Agent prompt：{definition.prompt_id}")
        if definition.model not in models:
            raise ValueError(f"{definition.definition_id} 引用了未知 model endpoint：{definition.model}")
        missing = definition.tools - tools.names
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"{definition.definition_id} 引用了不可用工具：{names}")
        if bool(definition.children) != (DELEGATE_TOOL in definition.tools):
            raise ValueError(f"{definition.definition_id} 的 children 与 {DELEGATE_TOOL} 可见性不一致")
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
