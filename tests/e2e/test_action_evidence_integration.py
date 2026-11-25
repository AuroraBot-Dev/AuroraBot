"""验证默认装配的执行证据、笔记引用、分页查询及恢复不重放。"""

import asyncio
import json
import sqlite3
from typing import cast

import pytest
from aurora_adapter.model.testing import FakeReply
from aurora_bot.assembly_config import CONFIG, WORK
from aurora_bot.work_notes import WorkNotes
from aurora_control import ExecutionRequest
from test_default_assembly import seed, setup


def configure(ctx, **options):
    seed(ctx)
    ctx.set(
        CONFIG,
        {
            **cast(dict, ctx.get(CONFIG)),
            "actions": {"enabled": True, "max_chars": 1024},
            "notes": {"enabled": True},
            "max_iterations": 32,
            **options,
        },
    )


def read_all(evidence, run, call):
    parts, offset = [], 0
    while True:
        page = evidence.read(run, call, offset)
        parts.append(page["text"])
        if page["next_offset"] is None:
            return json.loads("".join(parts))
        offset = page["next_offset"]


@pytest.mark.parametrize("streaming", [False, True])
def test_tool_note_reference_and_query_after_restart(tmp_path, streaming):
    async def scenario():
        host, assembly, ctx, _, clients, _, events, _ = setup(tmp_path)
        await host.start(configure=lambda: configure(ctx, streaming=streaming))
        reference = {}

        def respond(request):
            latest = request["messages"][-1]
            view = json.loads(next(m["content"] for m in request["messages"] if m["role"] == "user"))
            if latest["role"] != "tool":
                return FakeReply(tool_calls=({"id": "send", "name": "echo", "arguments": {"text": '消息😀\n"' * 500}},))
            if latest["tool_call_id"] == "send":
                action = next(item for item in view["actions"]["records"] if item["call_id"] == "send")
                assert action["outcome"] == "completed"
                reference.update(kind="tool_call", run_id=action["run_id"], call_id="send")
                return FakeReply(
                    tool_calls=(
                        {
                            "id": "remember",
                            "name": "notes_write",
                            "arguments": {
                                "note_id": "sent",
                                "expected_revision": 0,
                                "text": "已完成",
                                "status": "active",
                                "references": [reference],
                            },
                        },
                    )
                )
            return FakeReply(("已记录",))

        clients[0].respond = respond
        try:
            assert (await assembly.runtime.submit("执行并记录").run.wait()).status == "completed"
            assert events.count("tool.executed") == 1
            assert not any(dict(a.location).get("part") == "tool_results" for a in ctx.list(key=WORK))
        finally:
            await host.stop()
        assert assembly.action_evidence is not None and assembly.action_evidence._connection is None

        host, assembly, ctx, _, clients, _, events, _ = setup(tmp_path)
        await host.start()
        pages = []

        def retrieve(request):
            view = json.loads(next(m["content"] for m in request["messages"] if m["role"] == "user"))
            assert view["notes"]["records"][0]["references"] == [reference]
            latest = request["messages"][-1]
            offset = 0.0
            if latest["role"] == "tool" and latest["tool_call_id"].startswith("read-"):
                result = json.loads(latest["content"])
                assert result["status"] == "completed"
                page = result["value"]
                pages.append(page["text"])
                if page["next_offset"] is None:
                    return FakeReply(("核对原始回执",))
                offset = float(page["next_offset"])
            return FakeReply(
                tool_calls=(
                    {
                        "id": f"read-{len(pages)}",
                        "name": "actions_read",
                        "arguments": {
                            "run_id": reference["run_id"],
                            "call_id": reference["call_id"],
                            "offset": offset,
                        },
                    },
                )
            )

        try:
            assert clients[0].requests == [] and "tool.executed" not in events
            clients[0].respond = retrieve
            assert (await assembly.runtime.submit("核对原调用").run.wait()).status == "completed"
            record = json.loads("".join(pages))
            assert len(pages) > 1 and record["outcome"] == "completed"
            assert record["result"]["value"] == "工具:" + '消息😀\n"' * 500
            assert "tool.executed" not in events
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_cancel_keeps_unknown_despite_completed_note_and_does_not_replay(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clients, _, events, entered = setup(tmp_path, behavior="wait")
        await host.start(configure=lambda: configure(ctx))
        clients[0].respond = lambda request: FakeReply(
            tool_calls=(
                {"id": "first", "name": "echo", "arguments": {"text": "发送"}},
                {"id": "later", "name": "echo", "arguments": {"text": "稍后"}},
            )
        )
        submission = assembly.runtime.submit("执行")
        await entered.wait()
        run = submission.run.run_id
        await assembly.runtime.cancel(run)
        assert assembly.action_evidence is not None
        assert read_all(assembly.action_evidence, run, "first")["outcome"] == "unknown"
        assert read_all(assembly.action_evidence, run, "later")["outcome"] == "not_executed"
        WorkNotes(ctx, "main").write(
            {
                "note_id": "claim",
                "expected_revision": 0,
                "text": "已完成",
                "status": "active",
                "references": [{"kind": "tool_call", "run_id": run, "call_id": "first"}],
            },
            ExecutionRequest("note"),
            "write",
        )
        await host.stop()
        host, assembly, ctx, _, clients, _, events, _ = setup(tmp_path)
        await host.start()
        try:
            assert assembly.action_evidence is not None
            assert read_all(assembly.action_evidence, run, "first")["outcome"] == "unknown"
            assert clients[0].requests == [] and "tool.executed" not in events
            assert WorkNotes(ctx, "main").read("claim")["text"] == "已完成"
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_result_storage_failure_stops_batch_and_preserves_unknown(tmp_path, monkeypatch):
    async def scenario():
        host, assembly, ctx, _, clients, _, events, _ = setup(tmp_path)
        await host.start(configure=lambda: configure(ctx))
        clients[0].respond = lambda request: FakeReply(
            tool_calls=(
                {"id": "first", "name": "echo", "arguments": {"text": "发送"}},
                {"id": "later", "name": "echo", "arguments": {"text": "稍后"}},
            )
        )
        assert assembly.action_evidence is not None

        def fail(request, result):
            raise sqlite3.OperationalError("写入失败")

        monkeypatch.setattr(assembly.action_evidence, "finish", fail)
        try:
            submission = assembly.runtime.submit("执行")
            result = await submission.run.wait()
            assert result.status == "failed" and events.count("tool.executed") == 1
            assert read_all(assembly.action_evidence, submission.run.run_id, "first")["outcome"] == "unknown"
            assert read_all(assembly.action_evidence, submission.run.run_id, "later")["outcome"] == "not_executed"
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_disabled_does_not_create_database_or_advertise_tool(tmp_path):
    async def scenario():
        host, assembly, ctx, _, _, _, _, _ = setup(tmp_path)
        await host.start(configure=lambda: seed(ctx))
        try:
            assert assembly.action_evidence is None
            assert assembly.defaults is not None
            assert "actions_read" not in {item["name"] for item in assembly.defaults.tools.definitions()}
            assert not list(tmp_path.rglob("actions.sqlite3"))
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_all_view_sections_fit_minimum_budget_and_query_errors_are_explicit(tmp_path):
    from aurora_world.configuration import plugin as configuration_plugin
    from aurora_world.plugin import plugin as world_plugin

    async def scenario():
        host, assembly, ctx, _, clients, _, _, _ = setup(
            tmp_path, extra_plugins=(world_plugin(), configuration_plugin())
        )
        await host.start(configure=lambda: configure(ctx, archive={"enabled": True}, context_view={"max_chars": 1024}))

        def respond(request):
            text = next(m["content"] for m in request["messages"] if m["role"] == "user")
            assert len(text) <= 1024
            view = json.loads(text)
            assert all(view[name]["enabled"] for name in ("events", "environment", "notes", "actions"))
            results = [json.loads(m["content"]) for m in request["messages"] if m["role"] == "tool"]
            if results:
                assert [r["error"]["code"] for r in results] == [
                    "action_not_found",
                    "invalid_arguments",
                    "invalid_arguments",
                ]
                return FakeReply(("查询失败边界明确",))
            return FakeReply(
                tool_calls=(
                    {"id": "missing", "name": "actions_read", "arguments": {"run_id": "missing", "call_id": "missing"}},
                    {
                        "id": "boolean",
                        "name": "actions_read",
                        "arguments": {"run_id": "missing", "call_id": "missing", "offset": True},
                    },
                    {
                        "id": "foreign",
                        "name": "actions_read",
                        "arguments": {"run_id": "missing", "call_id": "missing", "instance_id": "other"},
                    },
                )
            )

        clients[0].respond = respond
        try:
            assert (await assembly.runtime.submit("核对").run.wait()).status == "completed"
        finally:
            await host.stop()

    asyncio.run(scenario())
