"""验证笔记引用、近期窗口过期与重启后的归档工具往返。"""

import asyncio
import json
from typing import cast

import pytest
from aurora_adapter.model import JsonValue, ToolCall
from aurora_adapter.model.testing import FakeReply
from aurora_bot.assembly_config import CONFIG, MESSAGES
from aurora_bot.event_archive import READ_EVENT
from aurora_bot.work_notes import NOTES
from aurora_core.json_data import encode_json
from aurora_world.configuration import plugin as configuration_plugin
from aurora_world.plugin import plugin as world_plugin
from test_default_assembly import seed, setup


def observation(request):
    return json.loads(next(message["content"] for message in request["messages"] if message["role"] == "user"))


def read_call(identity, reference, offset: JsonValue = 0) -> ToolCall:
    return {
        "id": identity,
        "name": "world_read_event",
        "arguments": {"journal_id": reference["journal_id"], "record_id": reference["record_id"], "offset": offset},
    }


@pytest.mark.parametrize("float_offset", [False, True])
def test_note_reference_reads_expired_event_in_pages_and_survives_restart(tmp_path, float_offset):
    async def scenario():
        clock = [10000.0]
        host, assembly, ctx, _, clients, _, _, _ = setup(
            tmp_path, extra_plugins=(world_plugin(), configuration_plugin())
        )
        assert assembly.world_records is not None
        assembly.world_records.now = lambda: clock[0]

        def configure():
            seed(ctx, tools=False)
            ctx.set(
                CONFIG,
                {
                    **cast(dict, ctx.get(CONFIG)),
                    "notes": {"enabled": True},
                    "archive": {"enabled": True, "max_chars": 1600},
                    "max_iterations": 32,
                },
            )

        await host.start(configure=configure)
        payload = {"text": '原始事件😀\n"\\' * 250, "status": "待核对"}
        record = assembly.world_records.append(source_id="sensor", message_id="alarm", payload=payload).record
        reference: dict[str, JsonValue] = {
            "kind": "world_event",
            "journal_id": record.position.journal_id,
            "record_id": record.record_id,
        }

        def remember(request):
            view = observation(request)
            assert "world_read_event" in view["notice"]
            if view["notes"]["records"]:
                return FakeReply(("已保留核对引用",))
            event = view["events"]["records"][0]
            assert event["record_id"] == reference["record_id"]
            return FakeReply(
                tool_calls=(
                    {
                        "id": "remember",
                        "name": "notes_write",
                        "arguments": {
                            "note_id": "inspection",
                            "expected_revision": 0,
                            "text": "稍后按引用核对原始事件",
                            "status": "active",
                            "references": [reference],
                        },
                    },
                )
            )

        clients[0].respond = remember
        try:
            assert (await assembly.runtime.submit("记住事件").run.wait()).status == "completed"
            stored = ctx.get(NOTES, location={"instance_id": "main"})
            clock[0] += 7200
            pages = []

            def retrieve(request):
                view = observation(request)
                assert view["events"]["records"] == []
                assert view["notes"]["records"][0]["references"] == [reference]
                assert {tool["name"] for tool in request["tools"]} == {
                    "notes_read",
                    "notes_write",
                    "notes_list",
                    "world_read_event",
                }
                latest = request["messages"][-1]
                if latest["role"] != "tool":
                    return FakeReply(tool_calls=(read_call("page-0", reference, 0.0 if float_offset else 0),))
                result = json.loads(latest["content"])
                assert result["status"] == "completed"
                page = result["value"]
                assert len(encode_json(page)) <= 1600
                assert page["journal_id"] == reference["journal_id"] and page["record_id"] == record.record_id
                assert page["source_id"] == "sensor" and page["message_id"] == "alarm"
                assert page["received_at"] == 10000 and page["sequence"] == record.position.sequence
                assert page["offset"] == sum(len(item["text"]) for item in pages)
                pages.append(page)
                if page["next_offset"] is None:
                    return FakeReply(("已读完原始事件，尚未执行外部动作",))
                offset = float(page["next_offset"]) if float_offset else page["next_offset"]
                return FakeReply(tool_calls=(read_call(f"page-{len(pages)}", reference, offset),))

            clients[0].respond = retrieve
            assert (await assembly.runtime.submit("核对旧事件").run.wait()).status == "completed"
            assert len(pages) > 1 and json.loads("".join(page["text"] for page in pages)) == payload
            assert ctx.get(NOTES, location={"instance_id": "main"}) == stored
            assert assembly.world_records.append(source_id="sensor", message_id="alarm", payload=payload).duplicate
            history = cast(dict, ctx.get(MESSAGES, location={"instance_id": "main"}))["messages"]
            calls = [call["id"] for message in history for call in message.get("tool_calls", [])]
            results = [message["tool_call_id"] for message in history if message["role"] == "tool"]
            assert calls == results
        finally:
            await host.stop()

        host, assembly, ctx, _, clients, _, _, _ = setup(
            tmp_path, extra_plugins=(world_plugin(), configuration_plugin())
        )
        assert assembly.world_records is not None
        assembly.world_records.now = lambda: clock[0]
        await host.start()
        pages.clear()
        try:
            assert clients[0].requests == [] and assembly.runtime.current is None
            assert ctx.get(NOTES, location={"instance_id": "main"}) == stored
            clients[0].respond = retrieve
            assert (await assembly.runtime.submit("重启后核对").run.wait()).status == "completed"
            assert json.loads("".join(page["text"] for page in pages)) == payload
            assert ctx.get(NOTES, location={"instance_id": "main"}) == stored
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_wrong_references_return_tool_errors_without_fallback(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clients, _, _, _ = setup(
            tmp_path, extra_plugins=(world_plugin(), configuration_plugin())
        )

        def configure():
            seed(ctx, tools=False)
            ctx.set(CONFIG, {**cast(dict, ctx.get(CONFIG)), "archive": {"enabled": True}})

        await host.start(configure=configure)
        assert assembly.world_records is not None
        record = assembly.world_records.append(source_id="sensor", message_id="alarm", payload="原文").record
        reference = {"journal_id": record.position.journal_id, "record_id": record.record_id}

        def respond(request):
            results = [json.loads(message["content"]) for message in request["messages"] if message["role"] == "tool"]
            if not results:
                return FakeReply(
                    tool_calls=(
                        read_call("wrong", {**reference, "journal_id": "other"}),
                        read_call("missing", {**reference, "record_id": "missing"}),
                        read_call("offset", reference, 1000),
                        read_call("boolean", reference, True),
                        read_call("fraction", reference, 1.5),
                        read_call("string", reference, "0"),
                        read_call("negative", reference, -1.0),
                        read_call("overflow", reference, 2**63),
                    )
                )
            assert [result["status"] for result in results] == ["failed"] * 8
            assert [result["error"]["code"] for result in results] == [
                "archive_wrong_journal",
                "archive_not_found",
                "archive_invalid_offset",
            ] + ["invalid_arguments"] * 5
            return FakeReply(("引用需核对",))

        clients[0].respond = respond
        try:
            assert (await assembly.runtime.submit("读取引用").run.wait()).status == "completed"
            assert assembly.world_records.get_by_id(record.record_id).payload == "原文"
        finally:
            await host.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("manual", [False, True])
def test_archive_requires_owned_world_and_rejects_manual_database_override(tmp_path, manual):
    async def scenario():
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path)

        def configure():
            seed(ctx, tools=False)
            config = {**cast(dict, ctx.get(CONFIG)), "archive": {"enabled": True}}
            if manual:
                config["tools"] = [{"tool": str(READ_EVENT), "instance_id": "foreign", "config": {"database": "other"}}]
            ctx.set(CONFIG, config)

        with pytest.raises(ValueError, match="archive.enabled"):
            await host.start(configure=configure)
        assert clients == [] and assembly.world_records is None
        assert not (tmp_path / "namespaces/ns-org.aurora.world/events.sqlite3").exists()

    asyncio.run(scenario())


def test_archive_disabled_does_not_advertise_tool(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clients, _, _, _ = setup(
            tmp_path, extra_plugins=(world_plugin(), configuration_plugin())
        )
        await host.start(configure=lambda: seed(ctx, tools=False))
        try:
            assert (await assembly.runtime.submit("查看当前观察").run.wait()).status == "completed"
            request = clients[0].requests[0]
            assert "tools" not in request and "world_read_event" not in observation(request)["notice"]
        finally:
            await host.stop()

    asyncio.run(scenario())
