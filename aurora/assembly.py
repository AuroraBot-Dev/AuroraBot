"""AuroraBot 的唯一组合根。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.runtime import AuroraRuntime
from src.engine import DELEGATE_TOOL, AgentTreeRunner
from src.prompt import PromptAssembler

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aurora.configuration import AuroraConfiguration
    from src.contracts import Model, Tool


def assemble_runtime(configuration: AuroraConfiguration, model: Model, tools: Iterable[Tool] = ()) -> AuroraRuntime:
    """把配置、Model 与 Tool 组合成可运行的项目实例。"""
    registered = tuple(tools)
    available = {DELEGATE_TOOL, *(tool.definition.name for tool in registered)}
    missing = configuration.root.tools - available
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"root references unavailable tools: {names}")
    assembler = PromptAssembler(
        configuration.prompt,
        max_characters=configuration.runner.max_prompt_characters,
    )
    runner = AgentTreeRunner(
        model,
        assembler,
        registered,
        max_depth=configuration.runner.max_depth,
        max_nodes=configuration.runner.max_nodes,
        max_steps=configuration.runner.max_steps,
    )
    return AuroraRuntime(runner, configuration.root)
