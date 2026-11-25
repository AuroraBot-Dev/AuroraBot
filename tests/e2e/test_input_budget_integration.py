"""验证默认装配的输入预算、历史恢复和超限失败不重复执行工具。"""

import asyncio
import json
from typing import cast

import pytest
from aurora_adapter.model import ModelError
from aurora_adapter.model.testing import FakeReply
from aurora_agent.input_budget import ModelInputBudget
from aurora_bot.assembly_config import CONFIG, MESSAGES, parse_config
from aurora_core.json_data import encode_json
from test_default_assembly import seed, setup


def configure(ctx, *, streaming=True, enabled=True, budget=2000):
    seed(ctx)
    ctx.set(
        CONFIG,
        {
            **cast(dict, ctx.get(CONFIG)),
            "streaming": streaming,
            "input_budget": {"enabled": enabled, "max_chars": budget},
        },
    )


@pytest.mark.parametrize("streaming", [False, True])
def test_long_history_selected_without_deletion_and_restored_after_restart(tmp_path, streaming):
    async def scenario():
        host, assembly, ctx, _, clients, _, events, _ = setup(tmp_path)
        await host.start(configure=lambda: configure(ctx, streaming=streaming))
        old = [
            {"role": "user", "content": "旧输入" * 2000},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "old", "name": "echo", "arguments": {"text": "旧"}}],
            },
            {"role": "tool", "tool_call_id": "old", "content": "旧结果"},
            {"role": "assistant", "content": "旧回复"},
        ]
        ctx.set(MESSAGES, {"messages": old, "guidance_sequence": 0, "pending": None}, location={"instance_id": "main"})

        def respond(request):
            assert len(encode_json(request)) <= 2000
            assert "旧输入" not in encode_json(request)
            notice = json.loads(request["messages"][0]["content"])
            assert notice["kind"] == "input_budget" and notice["omitted_messages"] >= 4
            latest = request["messages"][-1]
            if latest["role"] == "tool":
                assert latest["tool_call_id"] == "new"
                return FakeReply(("完成当前交流",))
            return FakeReply(tool_calls=({"id": "new", "name": "echo", "arguments": {"text": "当前"}},))

        clients[0].respond = respond
        try:
            assert (await assembly.runtime.submit("当前任务").run.wait()).status == "completed"
            assert events.count("tool.executed") == 1
            history = cast(dict, ctx.get(MESSAGES, location={"instance_id": "main"}))["messages"]
            assert history[:4] == old
            assert not any("input_budget" in m.get("content", "") for m in history)
        finally:
            await host.stop()
        host, assembly, ctx, _, clients, _, events, _ = setup(tmp_path)
        await host.start()
        try:
            assert clients[0].requests == []
            assert cast(dict, ctx.get(MESSAGES, location={"instance_id": "main"}))["messages"] == history
            clients[0].respond = respond
            assert (await assembly.runtime.submit("下一交流").run.wait()).status == "completed"
            assert events.count("tool.executed") == 1
            assert cast(dict, ctx.get(MESSAGES, location={"instance_id": "main"}))["messages"][:4] == old
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_oversized_tool_result_blocks_next_model_call_and_retry_does_not_repeat_tool(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clients, _, events, _ = setup(tmp_path)

        def options():
            configure(ctx)
            config = cast(dict, ctx.get(CONFIG))
            config["tools"][0]["config"]["prefix"] = "完整回执" * 1000
            ctx.set(CONFIG, config)

        await host.start(configure=options)
        clients[0].respond = lambda request: (
            FakeReply(("读取原结果",))
            if request["messages"][-1]["role"] == "tool"
            else FakeReply(tool_calls=({"id": "effect", "name": "echo", "arguments": {"text": "执行"}},))
        )
        try:
            result = await assembly.runtime.submit("原任务").run.wait()
            assert result.status == "failed" and result.error == "ModelInputBudgetExceeded"
            assert len(clients[0].requests) == 1 and events.count("tool.executed") == 1
            history = cast(dict, ctx.get(MESSAGES, location={"instance_id": "main"}))["messages"]
            assert history[-1]["role"] == "tool" and "完整回执" * 1000 in history[-1]["content"]
            assert assembly.defaults is not None
            assembly.defaults.input_budget = ModelInputBudget(12000)
            assert (await assembly.runtime.activate().wait()).status == "completed"
            assert events.count("tool.executed") == 1 and len(clients[0].requests) == 2
            assert sum(m.get("content") == "原任务" for m in clients[0].requests[-1]["messages"]) == 1
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_disabled_preserves_request_and_oversized_guidance_retry_is_not_duplicated(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path)
        await host.start(configure=lambda: configure(ctx, enabled=False))
        clients[0].respond = lambda request: FakeReply(("已收到",))
        try:
            assert (await assembly.runtime.submit("历史" * 2000).run.wait()).status == "completed"
            assert len(encode_json(clients[0].requests[0])) > 2000
            assert assembly.defaults is not None
            assembly.defaults.input_budget = ModelInputBudget(2000)
            result = await assembly.runtime.submit("新输入" * 2000).run.wait()
            assert result.status == "failed" and len(clients[0].requests) == 1
            assembly.defaults.input_budget = ModelInputBudget(30000)
            assert (await assembly.runtime.activate().wait()).status == "completed"
            assert len(clients[0].requests) == 2
            assert sum(m.get("content") == "新输入" * 2000 for m in clients[0].requests[-1]["messages"]) == 1
        finally:
            await host.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("value", [True, 1024.0, 1023, -1, "128000"])
def test_configuration_rejects_invalid_full_budget(value):
    with pytest.raises(ValueError):
        parse_config({"instance_id": "main", "model_role": "reasoning", "input_budget": {"max_chars": value}})


def test_default_configuration_keeps_budget_opt_in():
    assert parse_config({"instance_id": "main", "model_role": "reasoning"})["input_budget"] == {
        "enabled": False,
        "max_chars": 128000,
    }


def test_long_tool_task_compacts_and_restores_with_full_action_evidence(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clients, _, events, _ = setup(tmp_path)

        def options():
            configure(ctx, budget=8000)
            config = cast(dict, ctx.get(CONFIG))
            config.update(
                context_management={"enabled": True, "tool_result_chars": 2048, "summary_chars": 500},
                actions={"enabled": True, "max_chars": 2048},
                context_view={"enabled": False},
            )
            config["tools"][0]["config"]["prefix"] = "完整原始结果" * 700
            ctx.set(CONFIG, config)

        await host.start(configure=options)
        count = 0
        fail_summary = True

        def respond(request):
            nonlocal count
            if not request.get("tools"):
                if fail_summary:
                    return FakeReply(error=ModelError("模拟摘要失败"))
                return FakeReply(("继续核对工具结果，已执行动作不重复；未知结果查询 actions_read。",))
            assert len(encode_json(request)) <= 8000
            count += 1
            return (
                FakeReply(("任务完成",))
                if count == 8
                else FakeReply(
                    tool_calls=({"id": f"action-{count}", "name": "echo", "arguments": {"text": str(count)}},)
                )
            )

        clients[0].respond = respond
        try:
            result = await assembly.runtime.submit("逐步核对七项结果").run.wait()
            assert result.status == "failed" and result.error == "ModelError"
            interrupted = cast(dict, ctx.get(MESSAGES, location={"instance_id": "main"}))
            assert "compaction" not in interrupted and interrupted["pending"] is None
            fail_summary = False
            result = await assembly.runtime.activate().wait()
            assert result.status == "completed" and events.count("tool.executed") == 7
            context = cast(dict, ctx.get(MESSAGES, location={"instance_id": "main"}))
            assert context["compaction"]["end"] > 0 and len(context["messages"]) == 16
            assert context["messages"][0]["content"] == "逐步核对七项结果"
            assert any("context_summary" in encode_json(r) for r in clients[0].requests if r.get("tools"))
            observations = [json.loads(m["content"]) for m in context["messages"] if m["role"] == "tool"]
            assert all(o["value"]["truncated"] for o in observations)
            assert assembly.action_evidence is not None
            parts, offset = [], 0
            while True:
                page = assembly.action_evidence.read(observations[0]["value"]["read"]["run_id"], "action-1", offset)
                parts.append(page["text"])
                if page["next_offset"] is None:
                    break
                offset = page["next_offset"]
            assert json.loads("".join(parts))["result"]["value"] == "完整原始结果" * 700 + "1"
        finally:
            await host.stop()
        host, assembly, ctx, _, clients, _, events, _ = setup(tmp_path)
        await host.start()
        try:
            assert cast(dict, ctx.get(MESSAGES, location={"instance_id": "main"})) == context
            assert not clients[0].requests and "tool.executed" not in events
            clients[0].respond = lambda _: FakeReply(("已恢复",))
            assert (await assembly.runtime.submit("继续核对").run.wait()).status == "completed"
            assert "tool.executed" not in events
        finally:
            await host.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming,restart,initially_enabled", [(False, False, True), (True, True, False)])
def test_silent_completed_exchanges_remain_prunable(tmp_path, streaming, restart, initially_enabled):
    async def scenario():
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path)

        def options():
            configure(ctx, streaming=streaming, budget=1024, enabled=initially_enabled)
            ctx.set(CONFIG, {**cast(dict, ctx.get(CONFIG)), "tools": []})

        await host.start(configure=options)
        clients[0].respond = lambda request: FakeReply()
        inputs = [f"观察 {index}:" + "文" * 350 for index in range(6)]
        try:
            for text in inputs[:2]:
                assert (await assembly.runtime.submit(text).run.wait()).status == "completed"
            if restart:
                await host.stop()
                host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path)
                await host.start()
                assert clients[0].requests == []
                clients[0].respond = lambda request: FakeReply()
            assert assembly.defaults is not None
            assembly.defaults.input_budget = ModelInputBudget(1024)
            for text in inputs[2:]:
                assert (await assembly.runtime.submit(text).run.wait()).status == "completed"
                request = clients[0].requests[-1]
                assert len(encode_json(request)) <= 1024
                assert request["messages"][-1] == {"role": "user", "content": text}
                assert json.loads(request["messages"][0]["content"])["kind"] == "input_budget"
            context = cast(dict, ctx.get(MESSAGES, location={"instance_id": "main"}))
            assert context["messages"] == [{"role": "user", "content": text} for text in inputs]
            assert context["exchange_ends"] == list(range(1, 7))
            assert all(m["role"] != "assistant" for r in clients[0].requests for m in r["messages"])
        finally:
            await host.stop()

    asyncio.run(scenario())
