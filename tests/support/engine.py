from __future__ import annotations

from typing import Any

from aurora_bot.agents import AgentCatalog
from aurora_bot.engine import CognitionEngine
from aurora_bot.engine.hooks import REACT
from aurora_bot.kernel.context import SERVICES
from aurora_bot.kernel.hooks import service_namespace
from aurora_bot.tools import ToolRegistry
from aurora_kernel import Context, Host
from tests.support.prompt import _assembler


class EmptyMemory:
    async def recall(self, request: Any = None) -> None:
        return None


def make_engine(
    model: Any,
    definitions: Any,
    *,
    world: Any,
    tools: Any = (),
    memory: Any = None,
    assembler: Any = None,
    extensions: Any = (),
    process: Any = None,
    bot_id: str = "aurora:bot/default",
) -> CognitionEngine:
    ctx = Context()
    ctx.ensure(SERVICES).update(
        {
            "ai": model,
            "agents": AgentCatalog(definitions),
            "tools": ToolRegistry(tools),
            "memory": memory if memory is not None else EmptyMemory(),
            "prompt": assembler if assembler is not None else _assembler(),
        }
    )
    namespaces = (
        service_namespace("ai", "ai", methods=("resolve_endpoint",), asynchronous=("complete",)),
        service_namespace("agents", "agents", methods=("get",)),
        service_namespace(
            "tools",
            "tools",
            methods=("definitions_for", "scopes_for"),
            asynchronous=("execute",),
            attributes=("definitions",),
        ),
        service_namespace("memory", "memory", asynchronous=("recall",)),
        service_namespace("prompt", "prompt", methods=("assemble",)),
        REACT,
    )
    Host((*namespaces, *extensions), ctx=ctx).build()
    kwargs = {"process": process} if process is not None else {}
    runner = CognitionEngine(ctx, world, bot_id=bot_id, **kwargs)
    ctx[REACT.name]["runner"] = runner
    return runner
