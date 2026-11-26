"""验证长任务压缩边界、分片预算与失败时的摘要原子性。"""

import asyncio
import json
from copy import deepcopy

import pytest
from aurora_adapter.model import ModelError, ModelProtocolError
from aurora_adapter.model.testing import FakeModel, FakeReply
from aurora_agent.compaction import HistoryCompactor
from aurora_agent.input_budget import ModelInputBudget, ModelInputBudgetExceeded
from aurora_core.json_data import encode_json


def history():
    messages = [{"role": "user", "content": "目标：核对结果，未知动作不要重试"}]
    for index in range(6):
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "内部思考" * 100,
                    "thinking_blocks": [{"type": "thinking", "thinking": "核对", "signature": "signed"}],
                    "tool_calls": [
                        {"id": f"{index}-a", "name": "read", "arguments": {}},
                        {"id": f"{index}-b", "name": "read", "arguments": {}},
                    ],
                },
                {"role": "tool", "tool_call_id": f"{index}-a", "content": '文本"\\\n' * 180},
                {"role": "tool", "tool_call_id": f"{index}-b", "content": "unknown；actions_read run_id=r call_id=c"},
            ]
        )
    return messages


def test_compaction_chunks_preserve_recent_batches_and_restore_without_model_calls():
    async def scenario():
        messages = history()
        original = deepcopy(messages)
        client = FakeModel(lambda _: FakeReply(("目标：核对结果；unknown，不重试；actions_read run_id=r call_id=c",)))
        budget = ModelInputBudget(8000)
        compactor = HistoryCompactor(client, budget, summary_chars=500)
        request = {"messages": [{"role": "system", "content": "规则"}, *messages]}
        result, state = await compactor.apply(request, history_start=1, exchange_ends=[], state=None)
        assert state is not None and messages == original
        assert len(client.requests) > 1
        assert all(len(encode_json(value)) <= 8000 and not value.get("tools") for value in client.requests)
        assert result["messages"][-6:] == original[-6:]
        assert len(encode_json(result)) <= 8000
        fragments = "".join(
            json.loads(value["messages"][1]["content"])["history_fragment"] for value in client.requests
        )
        assert "目标：核对结果" in fragments and "unknown" in fragments and "内部思考" not in fragments
        restored = HistoryCompactor(client, budget, summary_chars=500)
        before = len(client.requests)
        again, same = await restored.apply(request, history_start=1, exchange_ends=[], state=state)
        assert again == result and same == state and len(client.requests) == before
        altered = deepcopy(request)
        altered["messages"][1]["content"] = "被外部改写"
        with pytest.raises(ValueError, match="不匹配"):
            await restored.apply(altered, history_start=1, exchange_ends=[], state=state)

    asyncio.run(scenario())


def test_archive_precedes_summary_and_durable_queue_failure_prevents_compaction_commit():
    async def scenario():
        records = []

        class Recorder:
            def archive(self, record):
                records.append(record)

            def remember(self, digest, text):
                assert digest == records[0]["digest"] and text == "摘要"
                raise OSError("磁盘写入失败")

        def respond(request):
            assert records and records[0]["run_id"] == "run"
            return FakeReply(("摘要",))

        messages = history()
        original = deepcopy(messages)
        compactor = HistoryCompactor(FakeModel(respond), ModelInputBudget(8000), summary_chars=500, recorder=Recorder())
        with pytest.raises(OSError, match="磁盘写入失败"):
            await compactor.apply({"messages": messages}, history_start=0, exchange_ends=[], state=None, run_id="run")
        assert messages == original and records[0]["messages"] == original[: records[0]["end"]]

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["error", "cancel", "timeout", "invalid"])
def test_incomplete_summary_does_not_mutate_history_or_leave_client_busy(failure):
    async def scenario():
        entered = asyncio.Event()
        client = FakeModel(lambda _: FakeReply(("临时摘要",)))
        original_complete = client.complete
        count = 0

        async def complete(request):
            nonlocal count
            count += 1
            if count == 2:
                entered.set()
                if failure == "error":
                    raise ModelError("模拟失败")
                if failure == "invalid":
                    return {"text": "x" * 600, "tool_calls": [], "finish_reason": "stop"}
                await asyncio.Event().wait()
            return await original_complete(request)

        client.complete = complete
        request = {"messages": history()}
        before = deepcopy(request)
        compactor = HistoryCompactor(
            client, ModelInputBudget(8000), summary_chars=500, timeout=0.05 if failure == "timeout" else 60
        )
        task = asyncio.create_task(compactor.apply(request, history_start=0, exchange_ends=[], state=None))
        if failure == "cancel":
            await entered.wait()
            task.cancel()
        expected = {
            "error": ModelError,
            "cancel": asyncio.CancelledError,
            "timeout": TimeoutError,
            "invalid": ModelProtocolError,
        }[failure]
        with pytest.raises(expected):
            await task
        assert request == before and client.active_streams == 0 and count == 2

    asyncio.run(scenario())


def test_fixed_input_and_unfinished_tool_batch_are_not_compressed():
    async def scenario():
        client = FakeModel(lambda _: FakeReply(("摘要",)))
        compactor = HistoryCompactor(client, ModelInputBudget(4000), summary_chars=500)
        request = {"messages": [{"role": "system", "content": "固定规则" * 1500}, *history()]}
        with pytest.raises(ModelInputBudgetExceeded) as failure:
            await compactor.apply(request, history_start=1, exchange_ends=[], state=None)
        assert failure.value.breakdown["system"] > 4000 and not client.requests
        with pytest.raises(ModelProtocolError, match="收齐|完整"):
            await compactor.apply({"messages": history()[:-1]}, history_start=0, exchange_ends=[], state=None)
        assert not client.requests

    asyncio.run(scenario())
