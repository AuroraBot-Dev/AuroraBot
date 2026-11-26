"""验证直接交流回执在真实调度结束边界与取消清理期间的关联。"""

import asyncio
import base64

import pytest
from aurora_bot.conversation import ConversationEndpoint
from aurora_bot.operations import RunOperations


def test_attachment_only_submission_deduplication_and_validation(standalone):
    async def scenario():
        async def infer():
            pass

        with standalone(infer) as (_, runtime, _, received):
            operations = RunOperations()
            operations.bind("main", runtime)
            endpoint = ConversationEndpoint(operations)
            request = {
                "session_id": endpoint.session_id,
                "instance_id": "main",
                "request_id": "files",
                "text": "",
                "files": [{"name": "photo.png", "media_type": "image/png", "data": "eA=="}],
            }
            runtime.start()
            try:
                status, receipt = await endpoint.handle("conversationSubmit", request)
                assert status == 200
                assert await endpoint.handle("conversationSubmit", request) == (status, receipt)
                if runtime.current:
                    await runtime.current.wait()
                assert len(received) == 1 and received[0]["payload"]["content"][0]["type"] == "image_url"
                different = {**request, "files": [{**request["files"][0], "data": "eQ=="}]}
                assert (await endpoint.handle("conversationSubmit", different))[0] == 409
                for files in (
                    [],
                    [{**request["files"][0], "data": "%%%"}],
                    [{**request["files"][0], "media_type": "text/html"}],
                    request["files"] * 9,
                ):
                    assert (
                        await endpoint.handle("conversationSubmit", {**request, "request_id": "bad", "files": files})
                    )[0] == 400
                text_file = {
                    "name": "note.txt",
                    "media_type": "text/plain",
                    "data": base64.b64encode("说明".encode()).decode(),
                }
                assert (
                    await endpoint.handle(
                        "conversationSubmit", {**request, "request_id": "text-file", "files": [text_file]}
                    )
                )[0] == 200
                if runtime.current:
                    await runtime.current.wait()
                assert received[-1]["payload"]["content"] == [{"type": "text", "text": "附件：note.txt\n说明"}]
            finally:
                await runtime.close()

    asyncio.run(scenario())


def test_receipts_follow_finish_boundary_and_cleanup_without_background_observers(standalone):
    async def scenario():
        entered, release, cleaning, cleaned = (asyncio.Event() for _ in range(4))

        async def infer():
            entered.set()
            await release.wait()

        async def cleanup():
            cleaning.set()
            await cleaned.wait()

        with standalone(infer, cleanup=cleanup) as (_, runtime, connect, received):
            operations = RunOperations()
            operations.bind("main", runtime)
            endpoint = ConversationEndpoint(operations, receipt_limit=3)
            scope = {"session_id": endpoint.session_id, "instance_id": "main"}

            async def call(action, data, status=200):
                actual, body = await endpoint.handle(f"conversation{action}", {**scope, **data})
                assert actual == status, body
                return body["result" if actual == 200 else "error"]

            followups = []

            async def finish(request):
                if not followups:
                    followups.append(await call("Submit", {"request_id": "next", "text": "下一轮"}))

            connect("finish", finish)
            runtime.start()
            try:
                first = await call("Submit", {"request_id": "first", "text": "开始"})
                await asyncio.wait_for(entered.wait(), 2)
                duplicate = await call("Submit", {"request_id": "first", "text": "开始"})
                assert duplicate == first
                conflict = await call("Submit", {"request_id": "first", "text": "不同内容"}, 409)
                assert conflict["code"] == "request_conflict"
                second = await call("Submit", {"request_id": "second", "text": "运行中引导"})
                assert second["run_id"] == first["run_id"] and second["sequence"] == first["sequence"] + 1
                release.set()
                await asyncio.wait_for(cleaning.wait(), 2)
                assert followups[0]["run_id"] != first["run_id"]
                query = await call("Query", {"request_id": "first"})
                assert query["run_status"] == "pending"
                cancelling = asyncio.create_task(call("Cancel", {"run_id": first["run_id"]}))
                await asyncio.sleep(0)
                assert not cancelling.done()
                cleaned.set()
                assert (await asyncio.wait_for(cancelling, 2))["cancelled"] is False
                assert (await call("Query", {"request_id": "first"}))["run_status"] == "completed"
                if runtime.current is not None:
                    await runtime.current.wait()
                assert (await call("Query", {"request_id": "next"}))["run_status"] == "completed"
                assert [item["payload"] for item in received] == ["开始", "运行中引导", "下一轮"]
                full = await call("Submit", {"request_id": "full", "text": "未接纳"}, 429)
                assert full["code"] == "receipt_limit"
                assert await call("Submit", {"request_id": "first", "text": "开始"}) == first
            finally:
                cleaned.set()
                await runtime.close()

    asyncio.run(scenario())


def test_cancel_waits_for_cleanup_and_rejects_new_guidance_until_done(standalone):
    async def scenario():
        entered, cleaning, cleaned = (asyncio.Event() for _ in range(3))

        async def infer():
            entered.set()
            await asyncio.Event().wait()

        async def cleanup():
            cleaning.set()
            await cleaned.wait()

        with standalone(infer, cleanup=cleanup) as (_, runtime, _, _):
            operations = RunOperations()
            operations.bind("main", runtime)
            endpoint = ConversationEndpoint(operations)
            scope = {"session_id": endpoint.session_id, "instance_id": "main"}
            runtime.start()
            try:
                _, first = await endpoint.handle("conversationSubmit", {**scope, "request_id": "one", "text": "开始"})
                run = {**scope, "run_id": first["result"]["run_id"]}
                await asyncio.wait_for(entered.wait(), 2)
                cancel = asyncio.create_task(endpoint.handle("conversationCancel", run))
                await asyncio.wait_for(cleaning.wait(), 2)
                assert not cancel.done()
                status, body = await endpoint.handle(
                    "conversationSubmit", {**scope, "request_id": "two", "text": "稍后"}
                )
                assert status == 409 and body["error"]["code"] == "busy"
                # HTTP 等待者结束不打断已经发起的 agent 清理。
                cancel.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await cancel
                cleaned.set()
                assert runtime.current is not None
                assert (await runtime.current.wait()).status == "cancelled"
                _, query = await endpoint.handle("conversationQuery", {**scope, "request_id": "one"})
                assert query["result"]["run_status"] == "cancelled"
                _, again = await endpoint.handle("conversationCancel", run)
                assert again["result"]["cancelled"] is False
            finally:
                cleaned.set()
                await runtime.close()

    asyncio.run(scenario())


def test_request_and_cancel_scope_isolated_between_instances(standalone):
    async def scenario():
        async def infer():
            await asyncio.Event().wait()

        with standalone(infer) as (_, first, _, _), standalone(infer) as (_, second, _, _):
            operations = RunOperations()
            operations.bind("first", first)
            operations.bind("second", second)
            endpoint = ConversationEndpoint(operations)
            message = {"session_id": endpoint.session_id, "request_id": "same", "text": "相同内容"}
            first.start()
            second.start()
            try:
                _, left = await endpoint.handle("conversationSubmit", {**message, "instance_id": "first"})
                _, right = await endpoint.handle("conversationSubmit", {**message, "instance_id": "second"})
                assert left["result"]["run_id"] != right["result"]["run_id"]
                assert left["result"]["sequence"] == right["result"]["sequence"] == 1
                _, mismatch = await endpoint.handle(
                    "conversationCancel",
                    {
                        "session_id": endpoint.session_id,
                        "instance_id": "second",
                        "run_id": left["result"]["run_id"],
                    },
                )
                assert mismatch["result"]["cancelled"] is False
                assert first.current is not None and not first.current.done
                assert second.current is not None and not second.current.done
            finally:
                await first.close()
                await second.close()

    asyncio.run(scenario())


def test_failed_run_keeps_original_receipt_without_retrying_work(standalone):
    async def scenario():
        async def infer():
            raise ValueError("内部信息不应进入公开回执")

        with standalone(infer) as (_, runtime, _, received):
            operations = RunOperations()
            operations.bind("main", runtime)
            endpoint = ConversationEndpoint(operations)
            query = {"session_id": endpoint.session_id, "instance_id": "main", "request_id": "one"}
            message = {**query, "text": "开始"}
            status, unavailable = await endpoint.handle("conversationSubmit", message)
            assert status == 503 and unavailable["error"]["code"] == "unavailable"
            runtime.start()
            try:
                _, accepted = await endpoint.handle("conversationSubmit", message)
                assert runtime.current is not None
                await runtime.current.wait()
                _, completed = await endpoint.handle("conversationQuery", query)
                assert completed["result"]["run_status"] == "failed"
                assert completed["result"]["error"] == "ValueError"
                assert await endpoint.handle("conversationSubmit", message) == (200, accepted)
                assert runtime.current is None and len(received) == 1
                runtime.stop_accepting()
                status, _ = await endpoint.handle("conversationSubmit", {**message, "request_id": "two"})
                assert status == 503
                assert await endpoint.handle("conversationSubmit", message) == (200, accepted)
            finally:
                await runtime.close()

    asyncio.run(scenario())
