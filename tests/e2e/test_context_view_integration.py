"""通过默认装配验证每轮视图、离线工具结果、直接交流和宿主恢复。"""

import asyncio
import json
from dataclasses import replace
from typing import cast

import pytest
from aurora_agent.tools import ToolInstance, ToolSpec
from aurora_bot.assembly_config import CONFIG, MESSAGES, WORK
from aurora_bot.conversation import CONVERSATION, ConversationEndpoint
from aurora_control import ExecutionPlug
from aurora_world.configuration import plugin as configuration_plugin
from aurora_world.plugin import plugin as world_plugin
from test_default_assembly import COMPONENT, TOOL, seed, setup


def view(request):
    return json.loads(next(message["content"] for message in request["messages"] if message["role"] == "user"))


@pytest.mark.parametrize("streaming", [False, True])
def test_tool_changes_refresh_view_without_persisting_snapshots_and_restore(tmp_path, streaming):
    async def scenario():
        plugins = (world_plugin(), configuration_plugin())
        host, assembly, ctx, registry, clients, _, _, _ = setup(tmp_path, extra_plugins=plugins)
        records = assembly.world_records
        assert records is not None
        records.select("weather", "weather")

        async def factory(*, ctx, storage, instance_id, input_state, output_state, config):
            async def execute(request):
                call = input_state.get(ctx, request)
                records.append(source_id="workshop", message_id="checked", payload="检查完成")
                records.append(source_id="weather", message_id="after", payload={"temperature": 20})
                output_state.set(ctx, request, config["prefix"] + call["arguments"]["text"])

            return ToolInstance(
                ExecutionPlug(
                    COMPONENT, execute, {"input": input_state, "output": output_state}, instance_id=instance_id
                )
            )

        entry = registry.get(TOOL)
        spec = entry.target
        assert isinstance(spec, ToolSpec)
        registry.replace(replace(entry, target=ToolSpec(spec.component, spec.definition, factory=factory)))

        def configure():
            seed(ctx)
            ctx.set(CONFIG, {**cast(dict, ctx.get(CONFIG)), "streaming": streaming, "system_prompt": "保持稳定的规则"})

        await host.start(configure=configure)
        try:
            initial = records.append(source_id="workshop", message_id="alarm", payload="需要检查").record
            records.append(source_id="weather", message_id="before", payload={"temperature": 18})
            endpoint = registry.get(CONVERSATION).target
            assert isinstance(endpoint, ConversationEndpoint)
            status, receipt = await endpoint.handle(
                "conversationSubmit",
                {"session_id": endpoint.session_id, "instance_id": "main", "request_id": "direct", "text": "请检查"},
            )
            assert status == 200 and receipt["result"]["accepted"]
            run = assembly.runtime.current
            assert run is not None and (await run.wait()).status == "completed"
            first, second = clients[0].requests
            assert first["messages"][0] == {"role": "system", "content": "保持稳定的规则"}
            assert view(first)["events"]["records"][0]["record_id"] == initial.record_id
            assert json.loads(view(first)["environment"]["records"][-1]["text"]) == {"temperature": 18}
            assert view(second)["events"]["records"][-1]["text"] == "检查完成"
            assert json.loads(view(second)["environment"]["records"][-1]["text"]) == {"temperature": 20}
            assert [message["role"] for message in second["messages"]] == [
                "system",
                "user",
                "user",
                "assistant",
                "tool",
            ]
            assert second["messages"][2]["content"] == "请检查"
            assert second["messages"][-2]["tool_calls"][0]["id"] == second["messages"][-1]["tool_call_id"]
            history = cast(dict, ctx.get(MESSAGES, location={"instance_id": "main"}))
            assert [item["content"] for item in history["messages"] if item["role"] == "user"] == ["请检查"]
            assert all(dict(address.location).get("part") != "model_input" for address in ctx.list(key=WORK))
        finally:
            await host.stop()
        snapshot = (tmp_path / "framework/ctx.json").read_text(encoding="utf-8")
        assert "business_context" not in snapshot

        host, assembly, ctx, _, clients, _, _, _ = setup(
            tmp_path, extra_plugins=(world_plugin(), configuration_plugin())
        )
        await host.start()
        try:
            assert not clients[0].requests
            assert ctx.get(MESSAGES, location={"instance_id": "main"}) == history
            assert (await assembly.runtime.submit("继续查看").run.wait()).status == "completed"
            request = clients[0].requests[0]
            assert view(request)["events"]["records"][-1]["text"] == "检查完成"
            assert len([message for message in request["messages"] if message["role"] == "user"]) == 3
        finally:
            await host.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("with_world,enabled", [(False, True), (True, False)])
def test_direct_input_works_without_world_or_with_view_disabled(tmp_path, with_world, enabled):
    async def scenario():
        plugins = (world_plugin(), configuration_plugin()) if with_world else ()
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path, extra_plugins=plugins)

        def configure():
            seed(ctx, tools=False)
            ctx.set(CONFIG, {**cast(dict, ctx.get(CONFIG)), "context_view": {"enabled": enabled}})

        await host.start(configure=configure)
        try:
            assert (await assembly.runtime.submit("直接交流").run.wait()).status == "completed"
            assert clients[0].requests[0]["messages"] == [{"role": "user", "content": "直接交流"}]
            if not with_world:
                assert assembly.world_records is None
                assert not (tmp_path / "namespaces/ns-org.aurora.world/events.sqlite3").exists()
        finally:
            await host.stop()

    asyncio.run(scenario())
