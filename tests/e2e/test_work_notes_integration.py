"""通过默认装配的真实工具协议验证工作笔记、冲突反馈和跨宿主恢复。"""

import asyncio
import json
from typing import cast

import pytest
from aurora_adapter.model import ToolCall
from aurora_adapter.model.testing import FakeReply
from aurora_bot.assembly_config import CONFIG, MESSAGES
from aurora_bot.work_notes import NOTE_TOOLS, NOTES
from aurora_control import ExecutionPlug, ExecutionRequest, component_entries
from aurora_core import Id
from aurora_world.configuration import plugin as configuration_plugin
from aurora_world.plugin import plugin as world_plugin
from test_default_assembly import seed, setup


def observation(request):
    return json.loads(next(message["content"] for message in request["messages"] if message["role"] == "user"))


def write_call(identity, revision, text, references) -> ToolCall:
    return {
        "id": identity,
        "name": "notes_write",
        "arguments": {
            "note_id": "inspection",
            "expected_revision": revision,
            "text": text,
            "status": "active",
            "references": references,
        },
    }


async def execute_calls(assembly, ctx, calls):
    assert assembly.defaults is not None
    executor = assembly.defaults.tools
    request = ExecutionRequest("notes-arguments")
    executor.request_state.set(ctx, request, {"turn_id": "arguments", "calls": calls})
    await executor.execute(request)
    return cast(dict, executor.output_state.get(ctx, request))["results"]


def test_integer_valued_float_arguments_work_through_tool_executor(tmp_path):
    async def scenario():
        host, assembly, ctx, _, _, _, _, _ = setup(tmp_path)

        def configure():
            seed(ctx, tools=False)
            ctx.set(CONFIG, {**cast(dict, ctx.get(CONFIG)), "notes": {"enabled": True}})

        await host.start(configure=configure)
        other = write_call("other", 0.0, "另一条笔记", [])
        other["arguments"]["note_id"] = "other"
        calls = [
            write_call("create", 0.0, "待核对", []),
            write_call("update", 1.0, "仍待核对", []),
            write_call("stale", 1.0, "过期覆盖", []),
            other,
            {"id": "first", "name": "notes_list", "arguments": {"limit": 1.0}},
            {"id": "next", "name": "notes_list", "arguments": {"limit": 1.0, "after": "inspection"}},
        ]
        try:
            results = await execute_calls(assembly, ctx, calls)
            assert [result["status"] for result in results] == [
                "completed",
                "completed",
                "failed",
                "completed",
                "completed",
                "completed",
            ]
            assert results[0]["value"]["revision"] == 1 and results[1]["value"]["revision"] == 2
            assert results[2]["error"]["code"] == "note_conflict" and results[2]["value"] == {"revision": 2}
            assert [note["note_id"] for note in results[4]["value"]["items"]] == ["inspection"]
            assert results[4]["value"]["next_after"] == "inspection"
            assert [note["note_id"] for note in results[5]["value"]["items"]] == ["other"]
            assert results[5]["value"]["next_after"] is None
            stored = cast(dict, ctx.get(NOTES, location={"instance_id": "main"}))["notes"]
            assert stored[0]["text"] == "仍待核对" and all(type(note["revision"]) is int for note in stored)
            assert type(calls[0]["arguments"]["expected_revision"]) is float
            assert type(calls[4]["arguments"]["limit"]) is float
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_invalid_integer_arguments_are_rejected_without_changing_notes(tmp_path):
    async def scenario():
        host, assembly, ctx, _, _, _, _, _ = setup(tmp_path)

        def configure():
            seed(ctx, tools=False)
            ctx.set(CONFIG, {**cast(dict, ctx.get(CONFIG)), "notes": {"enabled": True}})

        await host.start(configure=configure)
        try:
            assert (await execute_calls(assembly, ctx, [write_call("create", 0, "保留原文", [])]))[0][
                "status"
            ] == "completed"
            before = ctx.get(NOTES, location={"instance_id": "main"})
            calls = [
                write_call(f"write-{index}", value, "无效覆盖", [])
                for index, value in enumerate((True, False, 1.5, -1.0, "1"))
            ]
            calls.extend(
                {"id": f"list-{index}", "name": "notes_list", "arguments": {"limit": value}}
                for index, value in enumerate((True, False, 1.5, 0.0, 51.0, "1"))
            )
            results = await execute_calls(assembly, ctx, calls)
            assert all(
                result["status"] == "failed" and result["error"]["code"] == "invalid_arguments" for result in results
            )
            assert ctx.get(NOTES, location={"instance_id": "main"}) == before
        finally:
            await host.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("with_world", [False, True])
def test_notes_refresh_conflict_and_restore_without_automatic_work(tmp_path, with_world):
    async def scenario():
        plugins = (world_plugin(), configuration_plugin()) if with_world else ()
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path, extra_plugins=plugins)

        def configure():
            seed(ctx, tools=False)
            ctx.set(CONFIG, {**cast(dict, ctx.get(CONFIG)), "notes": {"enabled": True}})

        await host.start(configure=configure)
        references = []
        if with_world:
            assert assembly.world_records is not None
            record = assembly.world_records.append(source_id="sensor", message_id="alarm", payload="等待核对").record
            references = [
                {"kind": "world_event", "journal_id": record.position.journal_id, "record_id": record.record_id}
            ]
        rounds = []

        def respond(request):
            rounds.append(request)
            notes = observation(request)["notes"]["records"]
            if len(rounds) == 1:
                assert notes == []
                assert {tool["name"] for tool in request["tools"]} == {"notes_read", "notes_write", "notes_list"}
                return FakeReply(tool_calls=(write_call("create", 0, "计划发送通知，尚未执行", references),))
            result = json.loads(request["messages"][-1]["content"])
            if len(rounds) == 2:
                assert result["status"] == "completed" and result["value"]["revision"] == notes[0]["revision"] == 1
                assert notes[0]["references"] == references
                return FakeReply(
                    tool_calls=({"id": "read", "name": "notes_read", "arguments": {"note_id": "inspection"}},)
                )
            if len(rounds) == 3:
                assert result["value"]["text"] == "计划发送通知，尚未执行"
                return FakeReply(tool_calls=(write_call("stale", 0, "过期覆盖", references),))
            if len(rounds) == 4:
                assert result["status"] == "failed" and result["error"]["code"] == "note_conflict"
                assert notes[0]["revision"] == 1 and notes[0]["text"] != "过期覆盖"
                return FakeReply(tool_calls=(write_call("update", 1, "等待核实外部动作结果", references),))
            assert notes[0]["revision"] == 2 and notes[0]["text"] == "等待核实外部动作结果"
            return FakeReply(("已保留工作记录",))

        clients[0].respond = respond
        try:
            run = assembly.runtime.submit("保存检查计划").run
            assert (await run.wait()).status == "completed"
            stored = cast(dict, ctx.get(NOTES, location={"instance_id": "main"}))
            assert stored["notes"][0]["writer"]["run_id"] == run.run_id
            assert stored["notes"][0]["writer"]["call_id"] == "update"
            history = cast(dict, ctx.get(MESSAGES, location={"instance_id": "main"}))["messages"]
            assert [message["content"] for message in history if message["role"] == "user"] == ["保存检查计划"]
            assert len(rounds) == 5
        finally:
            await host.stop()

        plugins = (world_plugin(), configuration_plugin()) if with_world else ()
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path, extra_plugins=plugins)
        await host.start()
        try:
            assert clients[0].requests == [] and assembly.runtime.current is None
            assert ctx.get(NOTES, location={"instance_id": "main"}) == stored
            clients[0].respond = lambda _: FakeReply(("先核实结果",))
            assert (await assembly.runtime.submit("继续检查").run.wait()).status == "completed"
            assert observation(clients[0].requests[0])["notes"]["records"][0]["revision"] == 2
            assert ctx.get(NOTES, location={"instance_id": "main"}) == stored
            if not with_world:
                assert assembly.world_records is None
                assert not (tmp_path / "namespaces/ns-org.aurora.world/events.sqlite3").exists()
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_tools_are_explicit_and_note_state_survives_disabling(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path)

        def configure():
            seed(ctx, tools=False)
            ctx.set(CONFIG, {**cast(dict, ctx.get(CONFIG)), "notes": {"enabled": True}})

        await host.start(configure=configure)
        clients[0].respond = lambda request: (
            FakeReply(tool_calls=(write_call("create", 0, "稍后核对", []),))
            if not observation(request)["notes"]["records"]
            else FakeReply()
        )
        try:
            assert (await assembly.runtime.submit("记录").run.wait()).status == "completed"
            stored = ctx.get(NOTES, location={"instance_id": "main"})
        finally:
            await host.stop()
        path = tmp_path / "config/org.aurora.bot/config.toml"
        path.write_text(path.read_text(encoding="utf-8").replace("enabled = true", "enabled = false"), encoding="utf-8")
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path)
        await host.start()
        try:
            assert (await assembly.runtime.submit("直接交流").run.wait()).status == "completed"
            assert "tools" not in clients[0].requests[0]
            assert ctx.get(NOTES, location={"instance_id": "main"}) == stored
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_manual_tool_selection_cannot_override_note_owner(tmp_path):
    async def scenario():
        host, _, ctx, _, clients, _, _, _ = setup(tmp_path)

        def configure():
            seed(ctx, tools=False)
            ctx.set(
                CONFIG,
                {
                    **cast(dict, ctx.get(CONFIG)),
                    "tools": [
                        {"tool": str(NOTE_TOOLS["write"]), "instance_id": "foreign", "config": {"owner": "other"}}
                    ],
                },
            )

        with pytest.raises(ValueError, match="notes.enabled"):
            await host.start(configure=configure)
        assert clients == []

    asyncio.run(scenario())


def test_cancel_after_note_write_restores_result_without_repeating_write(tmp_path):
    async def scenario():
        host, assembly, ctx, registry, clients, _, _, _ = setup(tmp_path)

        def configure():
            seed(ctx, tools=False)
            ctx.set(CONFIG, {**cast(dict, ctx.get(CONFIG)), "notes": {"enabled": True}})

        await host.start(configure=configure)
        entered = asyncio.Event()

        async def hold(request):
            entered.set()
            await asyncio.Event().wait()

        identity = Id("dev.notes:handlers/hold_result")
        registry.register_many(component_entries(identity, hold, hold, provider="test"))
        assert assembly.defaults is not None
        assembly.defaults.tools.after.connect(ExecutionPlug(identity, hold))
        clients[0].respond = lambda _: FakeReply(tool_calls=(write_call("once", 0, "等待核对", []),))
        try:
            run = assembly.runtime.submit("记录").run
            await asyncio.wait_for(entered.wait(), timeout=2)
            assert await assembly.runtime.cancel(run.run_id)
            assert (await run.wait()).status == "cancelled"
            stored = ctx.get(NOTES, location={"instance_id": "main"})
            assert cast(dict, stored)["notes"][0]["revision"] == 1
            assert cast(dict, ctx.get(MESSAGES, location={"instance_id": "main"}))["pending"] is not None
        finally:
            await host.stop()
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path)
        await host.start()
        try:
            assert not clients[0].requests
            clients[0].respond = lambda _: FakeReply()
            assert (await assembly.runtime.submit("读取已有记录").run.wait()).status == "completed"
            assert ctx.get(NOTES, location={"instance_id": "main"}) == stored
            messages = clients[0].requests[0]["messages"]
            result = json.loads(next(message["content"] for message in messages if message["role"] == "tool"))
            assert result["status"] == "completed" and result["call_id"] == "once" and result["value"]["revision"] == 1
        finally:
            await host.stop()

    asyncio.run(scenario())
