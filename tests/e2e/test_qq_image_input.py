"""QQ 世界图片经两种 cadence 路径进入模型，并随对话恢复且不重复投递。"""

import asyncio
from collections.abc import Callable
from typing import cast

import pytest
from aurora_control import ExecutionRequest
from aurora_core.json_data import decode_json
from aurora_world import WorldView
from test_cadence import append, state, until
from test_cadence import configured as forwarding
from test_cadence_decision import configured as deciding
from test_cadence_decision import tick
from test_default_assembly import seed


def qq_payload():
    return {
        "kind": "mcp.event",
        "connection_id": "qq",
        "uri": "qq://events/inbox",
        "identity": "source_message",
        "message_id": "qq.event-1",
        "payload": {
            "kind": "qq.message.group",
            "scope": "qq:group:100",
            "summary": "这是什么？",
            "data": {
                "onebot": {
                    "post_type": "message",
                    "message_id": 123,
                    "group_id": 100,
                    "message": [
                        {"type": "text", "data": {"text": "这是什么？"}},
                        {"type": "image", "data": {"file": "a.jpg", "url": "https://cdn.example/a.jpg"}},
                    ],
                }
            },
        },
    }


@pytest.mark.parametrize("mode", ["forward", "decision"])
def test_qq_image_reaches_model_and_restores_without_replay(tmp_path, mode):
    async def scenario():
        messages = None
        checkpoint = None
        for restart in (False, True):
            configure: Callable[[], None]
            if mode == "decision":
                host, assembly, ctx, clients, clock, decisions, configure, _ = deciding(tmp_path)
                decisions.choice = "attend_events"
            else:
                host, assembly, ctx, _, clients, _, _, _ = forwarding(tmp_path)

                def configure_forwarding(ctx=ctx):
                    seed(ctx, tools=False)

                configure = configure_forwarding
            records = assembly.world_records
            assert records is not None
            records.configure(view=WorldView(max_event_chars=80))
            await host.start(configure=configure)
            try:
                if restart:
                    assert assembly.defaults is not None
                    restored = cast(dict, assembly.defaults.context_state.get(ctx, ExecutionRequest("inspect")))
                    assert restored["messages"] == messages
                    assert state(ctx) == checkpoint
                    assert append(assembly, source="qq/events", payload=qq_payload()).duplicate
                    if mode == "decision":
                        await tick(clock, ctx)
                    for _ in range(5):
                        await asyncio.sleep(0)
                    assert clients[0].requests == [] and len(state(ctx)["receipts"]) == 1
                    continue
                receipt = append(assembly, source="qq/events", payload=qq_payload())
                if mode == "decision":
                    await tick(clock, ctx)
                    view = decisions.requests[-1]["state"]["business"]["events"]["records"]
                    assert view[0]["abridged"] and "https://cdn.example/a.jpg" not in view[0]["text"]
                await until(lambda ctx=ctx: len(state(ctx)["receipts"]) == 1)
                await until(lambda assembly=assembly: assembly.runtime.current is None)
                assert state(ctx)["error"] is None
                incoming = [
                    message for message in clients[0].requests[0]["messages"] if isinstance(message["content"], list)
                ]
                assert len(incoming) == 1
                parts = incoming[0]["content"]
                assert parts[-1] == {"type": "image_url", "image_url": {"url": "https://cdn.example/a.jpg"}}
                origin = cast(dict, decode_json(parts[-2]["text"]))
                assert origin["record_id"] == receipt.record.record_id and origin["scope"] == "qq:group:100"
                assert origin["onebot_message_id"] == 123 and origin["segment_index"] == 1
                original = cast(dict, decode_json(parts[0]["text"]))
                assert original == qq_payload() if mode == "forward" else original["kind"] == "cadence_decision"
                assert records.get_by_id(receipt.record.record_id).payload == qq_payload()
                assert assembly.defaults is not None
                messages = cast(dict, assembly.defaults.context_state.get(ctx, ExecutionRequest("inspect")))["messages"]
                checkpoint = state(ctx)
            finally:
                await host.stop()

    asyncio.run(scenario())
