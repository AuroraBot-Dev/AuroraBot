"""从 TOML 配置创建默认 bot；模型和工具通过显式工厂提供，无需网络或密钥。"""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import tomli_w
from aurora_adapter.model import ChatRequest, ModelConfig
from aurora_adapter.model.config import ADAPTERS, BINDINGS, ModelAdapter
from aurora_adapter.model.plugin import plugin as adapter_plugin
from aurora_adapter.model.testing import FakeModel, FakeReply
from aurora_agent.model import plugin as model_plugin
from aurora_agent.react import plugin as react_plugin
from aurora_agent.react_defaults import plugin as defaults_plugin
from aurora_agent.tools import TOOLS, ToolInstance, ToolSpec
from aurora_agent.tools import plugin as tools_plugin
from aurora_bot.assembly import DefaultAssembly
from aurora_bot.assembly import plugin as assembly_plugin
from aurora_config import CONFIGURATION, configuration_component
from aurora_config import plugin as configuration_plugin
from aurora_control import ExecutionPlug, ExecutionRequest, component_entries
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import install_context
from aurora_core.discovery import register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.lifecycle import Lifecycle, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService
from configuration import configured_plugins

ADAPTER = Id("dev.example.default:adapters/fake")
TOOL = Id("dev.example.default:tools/echo")
COMPONENT = Id("dev.example.default:handlers/echo")


async def create_model(config: ModelConfig, *, api_key: str | None = None) -> FakeModel:
    """示例工厂按模型配置创建独立客户端，不读取凭证。"""

    def respond(request: ChatRequest) -> FakeReply:
        if not request["messages"]:
            return FakeReply()
        latest = request["messages"][-1]
        if not isinstance(latest["content"], str):
            return FakeReply(("此离线回显示例只处理文本。",))
        if latest["role"] == "user":
            return FakeReply(
                tool_calls=({"id": uuid4().hex, "name": "echo", "arguments": {"text": latest["content"]}},)
            )
        if latest["role"] == "tool":
            result = json.loads(latest["content"])
            return FakeReply((config.model, ":", str(result.get("value", result.get("error")))))
        return FakeReply()

    print(f"创建模型: {config.model}", flush=True)
    return FakeModel(respond)


async def create_tool(*, ctx, storage, instance_id, input_state, output_state, config) -> ToolInstance:
    """实例只使用分配的工作地址；可关闭资源通过 aclose 交给装配管理。"""

    async def execute(request):
        call = input_state.get(ctx, request)
        assert isinstance(call, dict)
        output_state.set(ctx, request, config.get("prefix", "") + call["arguments"]["text"])

    return ToolInstance(
        ExecutionPlug(COMPONENT, execute, {"input": input_state, "output": output_state}, instance_id=instance_id)
    )


async def run(args: argparse.Namespace) -> None:
    registry = bootstrap()
    register_plugins(
        registry,
        configured_plugins(
            (
                configuration_plugin(),
                adapter_plugin(),
                model_plugin(),
                react_plugin(),
                tools_plugin(),
                defaults_plugin(),
                assembly_plugin(),
            )
        ),
    )
    install_lifecycle_slots(registry)
    registry.register(
        RegistryEntry(ADAPTER, "adapter", ModelAdapter("chat", create_model), "default_example", register_to=ADAPTERS)
    )

    async def declared_execute(request):
        raise RuntimeError("工具执行必须绑定工厂创建的实例")

    registry.register_many(component_entries(COMPONENT, declared_execute, declared_execute, provider="default_example"))
    registry.register(
        RegistryEntry(
            TOOL,
            "tool",
            ToolSpec(
                COMPONENT,
                {
                    "name": "echo",
                    "description": "按配置前缀回显文本",
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                },
                factory=create_tool,
            ),
            "default_example",
            register_to=TOOLS,
        )
    )
    ctx, hooks = install_context(registry), HookConnections(registry)
    storage = StorageService(args.data_dir)
    assembly = DefaultAssembly(registry=registry, ctx=ctx, hooks=hooks, storage=storage)
    host = Lifecycle(
        ctx,
        hooks,
        (configuration_component(registry, ctx, hooks, storage), *assembly.components()),
        persistence=ContextPersistence(ctx, storage.snapshot_store()),
        storage=storage,
    )

    def select_profile() -> None:
        if args.profile is not None:
            value = ctx.get(BINDINGS)
            assert isinstance(value, dict)
            value["reasoning"] = args.profile
            path = args.data_dir / "config/org.aurora.adapter/model/bindings.toml"
            path.write_text(tomli_w.dumps(value), encoding="utf-8")
            ctx.set(BINDINGS, value)

    await host.start(configure=select_profile)
    try:
        assert assembly.agent is not None and assembly.defaults is not None
        print("装配已启动；尚未激活。", flush=True)
        if args.serve:
            from aurora_api.access import AccessPolicy, token_from_env
            from aurora_api.server import serve
            from aurora_bot.assembly_config import AGENTS, MESSAGES, RUN, WORK
            from aurora_bot.conversation import CONVERSATION

            async with serve(
                registry,
                keys=[AGENTS, MESSAGES, RUN, WORK],
                endpoints=[CONVERSATION, *([CONFIGURATION] if args.edit_config else [])],
                port=args.port,
                access=AccessPolicy(token=token_from_env(args.token_env), allowed_origins=tuple(args.allowed_origin)),
            ) as url:
                print(f"直接交流 API: {url}", flush=True)
                await asyncio.Event().wait()
        if args.text is not None or args.activate:
            handle = assembly.runtime.submit(args.text).run if args.text is not None else assembly.runtime.activate()
            outcome = await handle.wait()
            if outcome.status != "completed":
                raise RuntimeError(f"激活未完成：{outcome.status}，{outcome.error}")
            request = ExecutionRequest(handle.run_id)
            result = assembly.defaults.model.output_state.get(ctx, request)
            assert isinstance(result, dict)
            print(f"内部输出: {result['text']}")
    finally:
        await host.stop()
    print(f"快照: {args.data_dir / 'framework' / 'ctx.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="默认装配与模型绑定恢复的离线示例")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--text", help="写入一条引导，并显式执行一次激活")
    parser.add_argument("--activate", action="store_true", help="使用已有输入显式激活")
    parser.add_argument("--profile", choices=("primary", "secondary"), help="本次启动前更新并保存模型角色绑定")
    parser.add_argument("--serve", action="store_true", help="持续提供本机直接交流与 ctx API")
    parser.add_argument("--port", type=int, default=10270, help="本机 API 端口")
    parser.add_argument("--token-env", help="serve 模式访问令牌的环境变量名")
    parser.add_argument("--allowed-origin", action="append", default=[], help="允许的浏览器来源，可重复")
    parser.add_argument("--edit-config", action="store_true", help="在 serve 模式开放声明 TOML 配置编辑")
    try:
        asyncio.run(run(parser.parse_args()))
    except KeyboardInterrupt:
        print("已取消。")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
