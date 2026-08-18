"""Model、Tools 与 PromptAssembler 到 AgentTreeRunner 的构造阶段。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.engine import DELEGATE_TOOL, AgentTreeRunner

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aurora.configuration import AuroraConfiguration
    from src.contracts import Model, Tool
    from src.prompt import PromptAssembler


def assemble_engine(
    configuration: AuroraConfiguration,
    model: Model,
    assembler: PromptAssembler,
    tools: Iterable[Tool] = (),
) -> AgentTreeRunner:
    registered = tuple(tools)
    available = {DELEGATE_TOOL, *(tool.definition.name for tool in registered)}
    missing = configuration.root.tools - available
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"root references unavailable tools: {names}")
    return AgentTreeRunner(
        model,
        assembler,
        registered,
        max_depth=configuration.runner.max_depth,
        max_nodes=configuration.runner.max_nodes,
        max_steps=configuration.runner.max_steps,
    )
