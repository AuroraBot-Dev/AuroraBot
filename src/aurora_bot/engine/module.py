"""``aurora_bot.engine`` 的自描述模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_bot.contracts.process import RUN_PROCESS_MEDIA_TYPE, CognitionProcess
from aurora_bot.contracts.resource_content import RESOURCE_CONTENTS, ResourceContent
from aurora_bot.contracts.run_lifecycle import RUN_SCOPE_PATTERN
from aurora_bot.contracts.scope import ScopeDeclaration, ScopeKind
from aurora_bot.engine.config import EngineConfig
from aurora_bot.engine.hooks import REACT
from aurora_bot.engine.runtime import CognitionEngine
from aurora_bot.kernel import ModuleContext, module

if TYPE_CHECKING:
    from collections.abc import Mapping

    from aurora_bot.contracts.pkgs.agents import AgentCatalog
    from aurora_bot.contracts.pkgs.ai import Model
    from aurora_bot.contracts.pkgs.engine import CognitionRunner as CognitionRunnerPort


@module(
    name="engine",
    provides="engine",
    requires=(
        "engine",
        "prompt",
        "ai",
        "agents",
        "tools",
        "world",
        "memory",
        "bot",
    ),
    contributes=RESOURCE_CONTENTS,
    points=REACT.spec.points,
    handlers=REACT.spec.handlers,
    scopes=ScopeDeclaration(RUN_SCOPE_PATTERN, ScopeKind.RUN, "一次独立认知运行的因果台账；按证据引用展开。"),
)
def build(context: ModuleContext) -> CognitionRunnerPort:
    """过程资源来自实际被选中的运行器，不读取失选运行器的配置。"""
    runner = context.get_optional("engine")
    if runner is None:
        config = context.settings.resolve(EngineConfig)
        assembler = context.get("prompt")
        agents = context.get("agents")
        tools = context.get("tools")
        model = context.get("ai")
        _validate_cross_references(agents, assembler.catalog.agent_prompts, model, tools.names)
        runner = CognitionEngine(
            context.ctx,
            context.get("world"),
            bot_id=context.get("bot").bot_id,
            process=CognitionProcess(config.max_model_calls, config.max_tool_calls, config.max_context_chars),
        )
    context.ctx[REACT.name]["runner"] = runner
    process = runner.process_definition
    context.contribute(RESOURCE_CONTENTS, ResourceContent(process.ref, process.content, RUN_PROCESS_MEDIA_TYPE))
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


MODULE = build
