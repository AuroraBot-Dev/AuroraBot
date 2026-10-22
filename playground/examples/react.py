from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from rich.console import Console

from aurora_agent import CallStatus, RunSnapshot
from aurora_bot.agents import AgentCatalog
from aurora_bot.contracts import (
    AgentDefinition,
    ChatMessage,
    CognitionRequest,
    ModelRequest,
    ToolCall,
    ToolDefinition,
    ToolOutput,
)
from aurora_bot.contracts.model_binding import ModelBinding, ProviderDefinition
from aurora_bot.contracts.prompt import PromptFragment
from aurora_bot.contracts.resource import ResourceKey
from aurora_bot.engine import CognitionEngine
from aurora_bot.engine.hooks import REACT
from aurora_bot.kernel.context import SERVICES
from aurora_bot.kernel.hooks import service_namespace
from aurora_bot.prompt import PromptAssembler, PromptCatalog
from aurora_bot.tools import ToolRegistry
from aurora_bot.world import SqlAlchemyWorldJournal
from aurora_kernel import Context, Host, ModuleSpec, Namespace, namespace

console = Console(highlight=False, markup=False)
PROVIDER = ProviderDefinition(ResourceKey.parse("demo:ai/provider/local"), "fake", None, "UNUSED_DEMO_KEY")
ENDPOINT = ModelBinding(ResourceKey.parse("demo:ai/endpoint/local"), PROVIDER, "local")
PREFIX = "aurora:kernel/module/"
MEMORY = Namespace(ModuleSpec(f"{PREFIX}memory"))


@MEMORY.callpoint("recall")
def recall(ctx: Context, request: object) -> None:
    return None


class DemoModel:
    providers = (PROVIDER,)
    endpoints = (ENDPOINT,)

    def resolve_endpoint(self, endpoint_id: str) -> ModelBinding:
        if endpoint_id != str(ENDPOINT.key):
            raise ValueError(f"未知模型：{endpoint_id}")
        return ENDPOINT

    async def complete(self, request: ModelRequest) -> ChatMessage:
        if any(message.role == "tool" for message in request.messages):
            return ChatMessage.assistant("已经收到工具结果。")
        return ChatMessage.assistant(
            tool_calls=(ToolCall("echo", "demo:tool/definition/echo", {"value": "你好，ReAct"}),)
        )


class EchoTool:
    definition = ToolDefinition(
        "demo:tool/definition/echo",
        "返回输入文本",
        {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
    )

    async def execute(self, call: ToolCall) -> ToolOutput:
        console.print("  ToolRegistry → EchoTool.execute")
        return ToolOutput(str(call.arguments["value"]))


@namespace("demo.trace", requires=(REACT.name,))
def trace(ctx: Context) -> None:
    ctx["demo.trace"]["steps"] = 0


@trace.hook(f"{PREFIX}engine:before_step")
def before_step(ctx: Context, snapshot: RunSnapshot) -> None:
    pending = any(call.status is CallStatus.PENDING for call in snapshot.calls)
    console.rule(f"步骤 {ctx['demo.trace']['steps'] + 1} · {'工具执行' if pending else '推理'}")


@trace.hook(f"{PREFIX}engine:after_step")
def after_step(ctx: Context, snapshot: RunSnapshot) -> None:
    with ctx.transaction() as staged:
        staged["demo.trace"]["steps"] += 1
    console.print(f"  after_step → run={snapshot.run_id}, status={snapshot.status.value}")


@trace.hook(f"{PREFIX}engine:before_tool")
def before_tool(ctx: Context, run_id: str, call: ToolCall) -> None:
    console.print(f"  before_tool → {call.name}")


@trace.hook(f"{PREFIX}engine:after_tool")
def after_tool(ctx: Context, run_id: str, call: ToolCall, result: ToolOutput) -> None:
    console.print(f"  after_tool → status={result.status.value}")


@namespace("demo.reasoning", requires=(f"{PREFIX}ai",))
def custom(ctx: Context) -> None:
    ctx["demo.reasoning"]["requests"] = 0


@custom.hook(f"{PREFIX}ai:complete", priority=10)
async def reason(ctx: Context, request: ModelRequest) -> ChatMessage:
    with ctx.transaction() as staged:
        staged["demo.reasoning"]["requests"] += 1
    console.print("  reason → 选中 demo.reasoning，调用离线模型")
    response = await ctx[SERVICES]["ai"].complete(request)
    if response.tool_calls:
        return response
    return replace(response, content=f"自定义推理：{response.content}")


async def run(*, use_custom: bool) -> None:
    tool = EchoTool()
    definition = AgentDefinition(
        "demo:agent/definition/root",
        "演示 Agent",
        "demo:prompt/agent/root",
        str(ENDPOINT.key),
        frozenset({tool.definition.name}),
    )
    prompts = PromptCatalog(
        (
            PromptFragment(ResourceKey.parse("demo:prompt/system/identity"), "你是 Aurora。"),
            PromptFragment(ResourceKey.parse(definition.prompt_id), "调用回声工具，再回复结果。"),
        )
    )
    ctx = Context()
    ctx.ensure(SERVICES).update(
        ai=DemoModel(), prompt=PromptAssembler(prompts), agents=AgentCatalog((definition,)), tools=ToolRegistry((tool,))
    )
    modules = (
        service_namespace("ai", "ai", methods=("resolve_endpoint",), asynchronous=("complete",)),
        service_namespace("agents", "agents", methods=("get",)),
        service_namespace("prompt", "prompt", methods=("assemble",)),
        service_namespace("tools", "tools", methods=("definitions_for", "scopes_for"), asynchronous=("execute",)),
        MEMORY,
        REACT,
        trace,
    )
    host = Host((*modules, custom) if use_custom else modules, ctx=ctx).build()
    console.print(f"推理实现：{host.routes[f'{PREFIX}ai:complete'].handlers[0][0]}")
    with TemporaryDirectory(prefix="aurora-react-") as directory:
        world = SqlAlchemyWorldJournal(Path(directory) / "world.sqlite3")
        ctx[REACT.name]["runner"] = CognitionEngine(ctx, world, bot_id="demo:bot/aurora")
        try:
            result = await ctx.acall(
                f"{PREFIX}engine:execute",
                CognitionRequest("演示一次 ReAct", agent=definition.definition_id, run_id="demo"),
            )
            console.print(f"\n结果：{result.output}")
            console.print(f"步骤数：{ctx['demo.trace']['steps']}")
            finished = await world.commit("demo:run:finished")
            assert finished is not None
            console.print(f"持久结束状态：{finished.data['status']}")
        finally:
            await world.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="真实 engine + kernel + 离线 Model/Tool 的 ReAct 演示")
    parser.add_argument("--default", action="store_true", help="使用默认 reason 实现，对比自定义 hook")
    args = parser.parse_args()
    asyncio.run(run(use_custom=not args.default))


if __name__ == "__main__":
    main()
