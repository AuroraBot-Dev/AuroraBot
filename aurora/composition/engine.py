"""构造并导出 ``src.engine`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey
from aurora.composition.prompt import PROMPT_ASSEMBLER
from aurora.configuration.engine import ENGINE_CONFIG
from aurora.configuration.runtime import RUNTIME_CONFIG
from src.engine import DELEGATE_TOOL, AgentTreeRunner

if TYPE_CHECKING:
    from aurora.composer import CompositionContext


ENGINE_RUNNER = InstanceKey[AgentTreeRunner]("engine.runner")


def register(context: CompositionContext) -> None:
    configuration = context.config.get(ENGINE_CONFIG)
    runtime = context.config.get(RUNTIME_CONFIG)
    assembler = context.require(PROMPT_ASSEMBLER)
    available = {DELEGATE_TOOL, *(tool.definition.name for tool in context.tools)}
    missing = runtime.tools - available
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"root 引用了不可用工具：{names}")
    context.provide(
        ENGINE_RUNNER,
        AgentTreeRunner(
            context.model,
            assembler,
            context.tools,
            max_depth=configuration.max_depth,
            max_nodes=configuration.max_nodes,
            max_steps=configuration.max_steps,
        ),
    )
