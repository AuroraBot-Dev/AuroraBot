from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from rich.console import Console

from aurora_bot.agents import AgentCatalog
from aurora_bot.contracts import (
    AgentDefinition,
    AgentNode,
    AgentTree,
    ChatMessage,
    ModelRequest,
    ToolCall,
    ToolDefinition,
    ToolOutput,
)
from aurora_bot.contracts.engine_hooks import ENGINE_NAMESPACE, ReActHook
from aurora_bot.contracts.model_binding import ModelBinding, ProviderDefinition
from aurora_bot.contracts.prompt import PromptFragment
from aurora_bot.contracts.resource import ResourceKey
from aurora_bot.engine import CognitionEngine
from aurora_bot.engine.hooks import REACT
from aurora_bot.prompt import PromptAssembler, PromptCatalog
from aurora_bot.tools import ToolRegistry
from aurora_kernel import Context, Host, namespace

if TYPE_CHECKING:
    from aurora_bot.contracts.pkgs.ai import Model

console = Console(highlight=False, markup=False)
PROVIDER = ProviderDefinition(ResourceKey.parse("demo:ai/provider/local"), "fake", None, "UNUSED_DEMO_KEY")
ENDPOINT = ModelBinding(ResourceKey.parse("demo:ai/endpoint/local"), PROVIDER, "local")


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


@namespace("demo.trace", requires=(ENGINE_NAMESPACE,))
def trace(ctx: Context) -> None:
    ctx["demo.trace"]["steps"] = 0


@trace.hook(ReActHook.BEFORE_STEP)
def before_step(ctx: Context, tree: AgentTree, node: AgentNode, index: int) -> None:
    console.rule(f"步骤 {index + 1} · {'工具执行' if node.pending_calls else '推理'}")


@trace.hook(ReActHook.AFTER_STEP)
def after_step(ctx: Context, tree: AgentTree, node: AgentNode, index: int) -> None:
    with ctx.transaction() as staged:
        staged["demo.trace"]["steps"] += 1
    console.print(f"  after_step → node={node.node_id}, status={node.status.value}")


@trace.hook(ReActHook.BEFORE_TOOL)
def before_tool(ctx: Context, tree: AgentTree, node: AgentNode, call: ToolCall) -> None:
    console.print(f"  before_tool → {call.name}")


@trace.hook(ReActHook.AFTER_TOOL)
def after_tool(ctx: Context, tree: AgentTree, node: AgentNode, call: ToolCall, result: ToolOutput) -> None:
    console.print(f"  after_tool → status={result.status.value}")


@namespace("demo.reasoning", requires=(ENGINE_NAMESPACE,))
def custom(ctx: Context) -> None:
    ctx["demo.reasoning"]["requests"] = 0


@custom.hook(ReActHook.REASON, priority=10)
async def reason(ctx: Context, request: ModelRequest, model: Model) -> ChatMessage:
    with ctx.transaction() as staged:
        staged["demo.reasoning"]["requests"] += 1
    console.print("  reason → 选中 demo.reasoning，调用离线模型")
    response = await model.complete(request)
    if response.tool_calls:
        return response
    return replace(response, content=f"自定义推理：{response.content}")


async def run(*, use_custom: bool) -> None:
    host = Host((REACT, trace, custom) if use_custom else (REACT, trace)).build()
    route = host.routes[ReActHook.REASON]
    console.print(f"reason 实现：{route.handlers[0][0]}")
    tool = EchoTool()
    definition = AgentDefinition(
        "demo:agent/definition/root",
        "演示 Agent",
        "demo:prompt/agent/root",
        str(ENDPOINT.key),
        frozenset({tool.definition.name}),
        frozenset(),
    )
    prompts = PromptCatalog(
        (
            PromptFragment(ResourceKey.parse("demo:prompt/system/identity"), "你是 Aurora。"),
            PromptFragment(ResourceKey.parse(definition.prompt_id), "调用回声工具，再回复结果。"),
        )
    )
    engine = CognitionEngine(
        DemoModel(), PromptAssembler(prompts), AgentCatalog((definition,)), ToolRegistry((tool,)), hooks=host.ctx
    )
    result = await engine.run(AgentTree.create("demo", "root", definition, "演示一次 ReAct"))
    console.print(f"\n结果：{result.node('root').result}")
    console.print(f"步骤数：{host.ctx['demo.trace']['steps']}")
    console.print(f"最后一次 ctx 变更：{host.ctx.last_change}")


def main() -> None:
    parser = argparse.ArgumentParser(description="真实 engine + kernel + 离线 Model/Tool 的 ReAct 演示")
    parser.add_argument("--default", action="store_true", help="使用默认 reason 实现，对比自定义 hook")
    args = parser.parse_args()
    asyncio.run(run(use_custom=not args.default))


if __name__ == "__main__":
    main()
