"""配置到完整 AuroraRuntime 的最终组合阶段。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composition.engine import assemble_engine
from aurora.composition.prompt import assemble_prompt
from aurora.runtime import AuroraRuntime

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aurora.configuration import AuroraConfiguration
    from src.contracts import Model, Tool


def assemble_runtime(configuration: AuroraConfiguration, model: Model, tools: Iterable[Tool] = ()) -> AuroraRuntime:
    """按 prompt、engine、runtime 三阶段构造可运行的项目实例。"""
    registered = tuple(tools)
    assembler = assemble_prompt(configuration)
    runner = assemble_engine(configuration, model, assembler, registered)
    return AuroraRuntime(runner, configuration.root)
